"""Exercise a running real model worker without installing an input method."""
import argparse
import json
from pathlib import Path
import time

from .rime_bridge import Request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mailbox', default='.cache/rime-smoke/typing-agent-ipc')
    parser.add_argument('--output', default='benchmarks/rime-service-smoke.json')
    args = parser.parse_args()
    directory = Path(args.mailbox)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            status = json.loads((directory / 'worker-status.json').read_text())
            if status['state'] == 'ready' and time.time() - status['updated'] < 15:
                break
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.2)
    else:
        raise TimeoutError('Worker did not become ready')
    rows = []
    request_path = directory / 'integration-smoke.req'
    result_path = request_path.with_suffix('.res')
    try:
        for revision, pinyin, context, expected in [
            (1, 'pingguo', '我想吃一个新鲜的', '苹果'),
            (2, 'kaolv', '这个问题需要认真', '考虑'),
        ]:
            request = Request('integration-smoke', revision, pinyin, context)
            raw = request.encode()
            start = time.monotonic()
            request_path.write_bytes(raw)
            deadline = start + 30
            while time.monotonic() < deadline:
                try:
                    lines = result_path.read_text(encoding='ascii').splitlines()
                    if lines[:5] == raw.decode().splitlines() and lines[5] == 'ok':
                        candidates = [bytes.fromhex(line).decode() for line in lines[7:]]
                        assert candidates and candidates[0] == expected, candidates
                        rows.append({'pinyin': pinyin, 'expected': expected, 'candidates': candidates,
                                     'roundtrip_ms': (time.monotonic()-start)*1000})
                        break
                except FileNotFoundError:
                    pass
                time.sleep(0.05)
            else:
                raise TimeoutError('No matching response')
    finally:
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)
    report = {'scope': 'Real Qwen worker and mailbox protocol; not a Windows input-method UI test', 'rows': rows}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
