"""Versioned local mailbox protocol. No sockets, shell execution or keystroke injection."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import time


@dataclass(frozen=True)
class Request:
    session: str
    revision: int
    pinyin: str
    context: str

    def encode(self):
        return ('\n'.join(['TA1', self.session, str(self.revision),
                          self.pinyin.encode().hex(), self.context.encode().hex()]) + '\n').encode()

    @classmethod
    def decode(cls, raw):
        if len(raw) > 8192:
            raise ValueError('Request too large')
        lines = raw.decode('ascii').splitlines()
        if len(lines) != 5 or lines[0] != 'TA1' or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', lines[1]):
            raise ValueError('Invalid request header')
        if not re.fullmatch(r'[0-9]{1,12}', lines[2]):
            raise ValueError('Invalid revision')
        pinyin = bytes.fromhex(lines[3]).decode('utf-8')
        context = bytes.fromhex(lines[4]).decode('utf-8')
        if (pinyin != '@next' and not re.fullmatch(r"[a-z' ]{1,64}", pinyin)) or len(context) > 512:
            raise ValueError('Invalid request text')
        if pinyin == '@next' and not context:
            raise ValueError('Prediction requires committed or preview context')
        return cls(lines[1], int(lines[2]), pinyin, context)


def response_bytes(request, candidates, elapsed_ms, status='ok'):
    header = request.encode().decode('ascii')[:-1]
    return (header + '\n' + status + '\n' + str(round(elapsed_ms, 1)) + '\n' +
            ''.join(text.encode('utf-8').hex() + '\n' for text in candidates)).encode('ascii')


def publish_if_current(path, raw, response):
    """Lua validates the echoed revision too, covering changes after this check."""
    path = Path(path)
    try:
        if path.read_bytes() != raw:
            return False
    except FileNotFoundError:
        return False
    target = path.with_suffix('.res')
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(response)
    os.replace(temporary, target)
    return True


def cleanup_mailboxes(directory, ttl=60):
    now = time.time()
    for suffix in ('*.req', '*.res', '*.tmp'):
        for path in Path(directory).glob(suffix):
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', path.stem):
                continue
            try:
                if now - path.stat().st_mtime > ttl:
                    path.unlink()
            except FileNotFoundError:
                pass
