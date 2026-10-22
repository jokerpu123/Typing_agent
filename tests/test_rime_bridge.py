from pathlib import Path
import tempfile
import unittest
from typing_agent.rime_bridge import Request, response_bytes, publish_if_current


class BridgeTests(unittest.TestCase):
    def test_prediction_request(self):
        request = Request('session-next', 1, '@next', '我想吃')
        self.assertEqual(Request.decode(request.encode()), request)
        with self.assertRaises(ValueError):
            Request.decode(Request('session-next', 1, '@next', '').encode())
    def test_unicode_context_roundtrip(self):
        request = Request('session-1', 42, "xi'an", '陕西省的省会是')
        self.assertEqual(Request.decode(request.encode()), request)

    def test_reject_untrusted_paths_and_oversized_input(self):
        for request in [Request('../escape', 1, 'ni', ''), Request('ok', 1, 'a'*65, ''),
                        Request('ok', 1, 'ni', '字'*513)]:
            with self.assertRaises(ValueError):
                Request.decode(request.encode())

    def test_stale_response_is_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'session.req'
            first = Request('session', 1, 'ping', '').encode()
            latest = Request('session', 2, 'pingguo', '').encode()
            path.write_bytes(latest)
            self.assertFalse(publish_if_current(path, first, b'wrong'))
            self.assertFalse(path.with_suffix('.res').exists())
            self.assertTrue(publish_if_current(path, latest, b'correct'))
            self.assertEqual(path.with_suffix('.res').read_bytes(), b'correct')

    def test_response_echoes_context_and_revision(self):
        request = Request('s1', 3, 'pingguo', '我想吃')
        result = response_bytes(request, ['苹果'], 10).decode().splitlines()
        self.assertEqual(result[:5], request.encode().decode().splitlines())
        self.assertEqual(bytes.fromhex(result[7]).decode(), '苹果')
