import unittest

from typing_agent.decoding import PinyinConstraint, group_beam_search, normalize_pinyin


READINGS = {
    '苹': ('ping',), '评': ('ping',), '果': ('guo',), '过': ('guo',),
    '重': ('zhong', 'chong'), '庆': ('qing',), '西': ('xi',),
    '安': ('an',), '先': ('xian',), '梨': ('li',),
}


class FakeBackend:
    token_text = {0: '苹', 1: '评', 2: '果', 3: '过', 4: '梨'}

    def log_probs(self, prefix):
        # Illegal 梨 wins unconstrained. A global top-k before masking would fail.
        if not prefix:
            return {0: -1.1, 1: -1.2, 2: -10., 3: -10., 4: -0.9}
        return {0: -10., 1: -10., 2: -0.1, 3: -3., 4: -10.}


class DecodingTests(unittest.TestCase):
    def setUp(self):
        self.constraint = PinyinConstraint(lambda char: READINGS.get(char, ()))

    def test_constraints_before_pruning(self):
        result = group_beam_search(FakeBackend(), self.constraint, 'pingguo', beam_width=1, groups=1)
        self.assertEqual(result[0].text, '苹果')
        self.assertAlmostEqual(result[0].log_probability, -1.2)

    def test_group_diversity_and_deduplication(self):
        result = group_beam_search(FakeBackend(), self.constraint, 'pingguo', beam_width=2, groups=2)
        self.assertEqual({c.text for c in result}, {'苹果', '评果'})

    def test_multiple_char_token_and_polyphony(self):
        self.assertEqual(self.constraint.advance('chongqing', frozenset({0}), '重庆'), frozenset({9}))

    def test_explicit_boundaries(self):
        self.assertFalse(self.constraint.advance("xi'an", frozenset({0}), '先'))
        self.assertEqual(self.constraint.advance("xi'an", frozenset({0}), '西安'), frozenset({5}))

    def test_no_invalid_or_partial_results(self):
        self.assertEqual(group_beam_search(FakeBackend(), self.constraint, 'nihao'), [])
        self.assertEqual(group_beam_search(FakeBackend(), self.constraint, 'pingguo', max_steps=1), [])

    def test_input_validation(self):
        self.assertEqual(normalize_pinyin('LÜ se'), "lv'se")
        for value in ('', '   ', 'ni3', '$', "''"):
            with self.assertRaises(ValueError):
                normalize_pinyin(value)
        with self.assertRaises(ValueError):
            group_beam_search(FakeBackend(), self.constraint, 'ping', beam_width=3, groups=2)


if __name__ == '__main__':
    unittest.main()
