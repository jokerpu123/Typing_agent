import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('pypinyin'), 'Install model extra to test real readings')
class PinyinIntegrationTests(unittest.TestCase):
    def test_real_readings(self):
        from typing_agent.transformers_backend import make_constraint
        constraint = make_constraint()
        for text, spelling in [('苹果', 'pingguo'), ('重庆', 'chongqing'), ('绿色', 'lvse')]:
            with self.subTest(text=text):
                self.assertIn(len(spelling), constraint.advance(spelling, frozenset({0}), text))
        self.assertFalse(constraint.advance('pingguo', frozenset({0}), '梨'))
