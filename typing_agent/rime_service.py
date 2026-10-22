"""Resident single-model worker for the RIME Lua mailbox adapter."""
import argparse
from collections import OrderedDict
import json
import os
from pathlib import Path
import time

from .rime_bridge import Request, response_bytes, publish_if_current, cleanup_mailboxes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='D:/models/Qwen3-1.7B-Base')
    parser.add_argument('--mailbox', default='D:/typing-agent/rime-user/typing-agent-ipc')
    args = parser.parse_args()
    directory = Path(args.mailbox)
    directory.mkdir(parents=True, exist_ok=True)
    # OS releases this byte-range lock on exit, including crashes.
    import msvcrt
    lock = (directory / 'worker.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('A worker is already running for this mailbox')
    status_path = directory / 'worker-status.json'

    def status(state):
        status_path.write_text(json.dumps({'state': state, 'pid': os.getpid(),
                                         'updated': time.time(), 'model': args.model}), encoding='utf-8')

    status('loading')
    os.environ.setdefault('HF_DEACTIVATE_ASYNC_LOAD', '1')
    from .transformers_backend import TransformersBackend, make_constraint
    from .decoding import group_beam_search
    backend = TransformersBackend(args.model, '')
    constraint = make_constraint()
    backend.set_context('我想吃')
    backend.predict_next_words()  # warm the CUDA path before advertising readiness
    cache = OrderedDict()
    processed = {}
    status('ready')
    print('RIME worker ready', flush=True)
    last_cleanup = 0
    try:
        while True:
            if time.monotonic() - last_cleanup > 5:
                cleanup_mailboxes(directory)
                processed = {p: value for p, value in processed.items() if p.exists()}
                status('ready')
                last_cleanup = time.monotonic()
            paths = sorted(directory.glob('*.req'), key=lambda p: (not p.stem.endswith('-next'), p.name))
            for path in paths[:128]:
                try:
                    if time.time() - path.stat().st_mtime < (0.05 if path.stem.endswith('-next') else 0.15):
                        continue  # debounce: rapid typing only submits the latest input
                    with path.open('rb') as source:
                        raw = source.read(8193)
                    if processed.get(path) == raw:
                        continue
                    request = Request.decode(raw)
                    if path.stem != request.session:
                        continue
                    start = time.perf_counter()
                    key = (request.pinyin, request.context)
                    if key not in cache:
                        backend.set_context(request.context)
                        if request.pinyin == '@next':
                            cache[key] = backend.predict_next_words()
                        else:
                            results = group_beam_search(backend, constraint, request.pinyin)
                            # Avoid unlikely filler candidates solely for diversity.
                            cache[key] = [c.text for c in results[:3]
                                          if c.log_probability >= results[0].log_probability - 8]
                        if len(cache) > 64:
                            cache.popitem(last=False)
                    cache.move_to_end(key)
                    elapsed = (time.perf_counter() - start) * 1000
                    publish_if_current(path, raw, response_bytes(request, cache[key], elapsed))
                    processed[path] = raw
                    print(f'completed mode={"predict" if request.pinyin == "@next" else "pinyin"} candidates={len(cache[key])} latency_ms={elapsed:.1f}', flush=True)
                except (ValueError, UnicodeError, FileNotFoundError, PermissionError):
                    continue
            time.sleep(0.05)
    finally:
        status('stopped')
        lock.close()


if __name__ == '__main__':
    main()
