"""Resumable HTTP range fallback for the pinned official model weights."""
import argparse
import hashlib
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .download_model import check_space

REVISION = 'ea980cb0a6c2ae4b936e82123acc929f1cec04c1'
SHA256 = '6df85b39330e5a425ee36253d0f894e4387e4f0a15b9c53cb467d668e6b3a841'
URL = f'https://huggingface.co/Qwen/Qwen3-1.7B-Base/resolve/{REVISION}/model.safetensors'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--source', choices=['huggingface', 'modelscope'], default='huggingface')
    args = parser.parse_args()
    url = URL if args.source == 'huggingface' else 'https://modelscope.cn/models/Qwen/Qwen3-1.7B-Base/resolve/master/model.safetensors'
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    partial = destination / 'model.safetensors.partial'
    position = partial.stat().st_size if partial.exists() else 0
    with requests.get(url, headers={'Range': 'bytes=0-0'}, stream=True, timeout=(15, 30)) as response:
        response.raise_for_status()
        total = int(response.headers['Content-Range'].split('/')[-1])
    check_space(destination, max(0, total - position) + 500_000_000)
    if position > total:
        raise RuntimeError('Partial file is larger than the pinned remote file')
    started = time.monotonic()
    chunk_size = 16 * 1024 * 1024
    def fetch_range(start):
        end = min(start + chunk_size, total) - 1
        for attempt in range(3):
            try:
                # Query avoids intermediary caches serving a different cached range.
                with requests.get(url + f'?range_start={start}',
                                  headers={'Range': f'bytes={start}-{end}'},
                                  timeout=(15, 45)) as response:
                    response.raise_for_status()
                    expected = f'bytes {start}-{end}/{total}'
                    if response.status_code != 206 or response.headers.get('Content-Range') != expected:
                        raise RuntimeError('Server did not honor requested byte range')
                    data = response.content
                    if len(data) != end - start + 1:
                        raise RuntimeError('Incomplete response')
                return data
            except (requests.RequestException, RuntimeError):
                if attempt == 2:
                    raise
                time.sleep(1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        while position < total:
            starts = list(range(position, min(position + 8 * chunk_size, total), chunk_size))
            # Bound memory to eight chunks and append in order for resumability.
            for data in pool.map(fetch_range, starts):
                with partial.open('ab') as output:
                    output.write(data)
                position += len(data)
                print(f'{position}/{total} bytes ({position / total:.1%}), {time.monotonic()-started:.0f}s', flush=True)
    digest = hashlib.sha256()
    with partial.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != SHA256:
        raise RuntimeError('SHA256 mismatch: retaining partial file for inspection')
    os.replace(partial, destination / 'model.safetensors')
    print('SHA256 verified; model.safetensors ready', flush=True)


if __name__ == '__main__':
    main()
