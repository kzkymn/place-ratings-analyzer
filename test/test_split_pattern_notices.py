#!/usr/bin/env python3
"""
Test suite for the "split rating" wording added to x1xxx/xx1xx/xx213/x3xxx/1xxxx.

These five patterns all involve a low-star rating (or, for x3xxx, the neutral
★3) taking an unexpectedly high rank position - a signal that opinions are
split rather than uniformly positive. The composition instruction ("list
this store separately from the recommendation list") is written directly
into each pattern's warning_text in data/rating_patterns.csv, so it travels
with that specific store's own result data (rating_advice.warning_text)
rather than being stated only once, generically, in the tool description.
Additionally, _check_star5_dominance runs unconditionally on every
distribution regardless of which pattern matched (see
src/rating_analyzer.py's analyze_distribution), so a split-pattern store
that also has an extreme star5 ratio gets a second, independent backstop via
star5_dominance_review_required (src/server.py's _build_star5_dominance_flag)
- though a split-pattern store without an extreme star5 ratio still relies
on warning_text alone.

Each pattern's warning_text must only name star ratings that the pattern's
rank columns actually guarantee - e.g. x1xxx only guarantees rank_2=★1, not
that rank_1=★5, so the text must not name ★5 specifically (2026-07-19 design
review caught this exact bug in an early draft).
"""
import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer


REPUTATION_RISK_WORDS = ('疑わし', 'サクラ', '不自然', '断定', '避け', '危険')


class TestSplitPatternNotices(unittest.TestCase):

    def setUp(self):
        self.analyzer = RuleBasedRatingAnalyzer('data/rating_patterns.csv')

    def _analyze(self, rating_dist):
        return self.analyzer.analyze_distribution(rating_dist)

    # ---- x1xxx (★1 is rank_2) ----

    def test_x1xxx_advice_states_split_as_unconditional_fact(self):
        result = self._analyze({5: 100, 1: 80, 4: 60, 3: 40, 2: 20})
        self.assertEqual(result['pattern'], 'x1xxx')
        self.assertIn('2番目', result['advice_text'])
        self.assertIn('評価が割れている', result['advice_text'])

    def test_x1xxx_warning_instructs_reading_star1_and_star2(self):
        result = self._analyze({5: 100, 1: 80, 4: 60, 3: 40, 2: 20})
        warning = result['warning_text']
        self.assertIn('★1・★2', warning)
        self.assertIn('候補の一覧とは別に', warning)
        self.assertIn('口コミを確認してから検討してほしい店', warning)

    def test_x1xxx_warning_does_not_assume_star5_is_rank1(self):
        """rank_1 is a wildcard in x1xxx (x,1,x,x,x) - it need not be ★5.

        A concrete counter-example: pattern 21534 (★2 most frequent, ★1
        second) still matches x1xxx, and there ★5 is only the third most
        common rating. The template must not name ★5 specifically.
        """
        result = self._analyze({2: 100, 1: 80, 5: 60, 3: 40, 4: 20})
        self.assertEqual(result['pattern'], 'x1xxx')
        self.assertNotIn('★5', result['warning_text'])

    def test_x1xxx_warning_does_not_use_bare_self_pronoun(self):
        """'自分' alone is ambiguous once warning_text is read by the LLM,
        not the human user directly; the established convention is always
        'ユーザー' (see general_disclaimer / tool description precedent)."""
        result = self._analyze({5: 100, 1: 80, 4: 60, 3: 40, 2: 20})
        self.assertNotIn('自分', result['warning_text'])

    # ---- xx1xx (★1 is rank_3) ----

    def test_xx1xx_advice_states_split_as_unconditional_fact(self):
        result = self._analyze({5: 100, 4: 80, 1: 60, 2: 40, 3: 20})
        self.assertEqual(result['pattern'], 'xx1xx')
        self.assertIn('3番目', result['advice_text'])
        self.assertIn('評価が割れている', result['advice_text'])

    def test_xx1xx_warning_matches_x1xxx_warning(self):
        """Same underlying fact (★1 guaranteed to rank ahead of at least two
        other star values) and same action - the two rows share warning_text
        verbatim (kept as direct CSV duplication for now, not centralized -
        see feedback_defer_abstraction_until_validated_by_cases)."""
        x1xxx_result = self._analyze({5: 100, 1: 80, 4: 60, 3: 40, 2: 20})
        xx1xx_result = self._analyze({5: 100, 4: 80, 1: 60, 2: 40, 3: 20})
        self.assertEqual(xx1xx_result['warning_text'], x1xxx_result['warning_text'])

    # ---- xx213 (★2 > ★1 > ★3, i.e. ★3 is the rarest rating) ----

    def test_xx213_advice_states_the_inversion_as_fact(self):
        result = self._analyze({4: 100, 5: 80, 2: 60, 1: 40, 3: 20})
        self.assertEqual(result['pattern'], 'xx213')
        self.assertIn('評価が割れている', result['advice_text'])

    def test_xx213_warning_instructs_reading_star1_and_star2(self):
        result = self._analyze({4: 100, 5: 80, 2: 60, 1: 40, 3: 20})
        warning = result['warning_text']
        self.assertIn('★1・★2', warning)
        self.assertIn('口コミを確認してから検討してほしい店', warning)

    # ---- x3xxx (★3 is rank_2; rank_1 is unconstrained) ----

    def test_x3xxx_advice_states_split_as_unconditional_fact(self):
        result = self._analyze({5: 100, 3: 80, 4: 60, 2: 40, 1: 20})
        self.assertEqual(result['pattern'], 'x3xxx')
        self.assertIn('2番目', result['advice_text'])
        self.assertIn('評価が割れている', result['advice_text'])

    def test_x3xxx_warning_does_not_assume_star1_and_star2_are_prominent(self):
        """Only rank_2=★3 is guaranteed; ★1/★2's positions are wildcards,
        so the warning must not tell the reader to check '★1・★2' the way
        x1xxx/xx1xx/xx213 do (2026-07-19 design review caught this)."""
        result = self._analyze({5: 100, 3: 80, 4: 60, 2: 40, 1: 20})
        self.assertNotIn('★1・★2', result['warning_text'])
        self.assertIn('主な評価', result['warning_text'])
        self.assertIn('口コミを確認してから検討してほしい店', result['warning_text'])

    # ---- 1xxxx (★1 is rank_1, i.e. most frequent - not a "split", but a
    # uniformly low-rated store that must not be buried in a list either) ----

    def test_1xxxx_warning_only_names_star1(self):
        """Unlike x1xxx/xx1xx/xx213, there is no guaranteed second cluster
        to compare against - only ★1 being dominant is guaranteed."""
        result = self._analyze({1: 100, 5: 80, 4: 60, 3: 40, 2: 20})
        self.assertEqual(result['pattern'], '1xxxx')
        warning = result['warning_text']
        self.assertIn('★1', warning)
        self.assertNotIn('★2', warning)
        self.assertIn('口コミを確認してから検討してほしい店', warning)

    def test_1xxxx_warning_avoids_reputation_risk_wording(self):
        result = self._analyze({1: 100, 5: 80, 4: 60, 3: 40, 2: 20})
        combined = result['advice_text'] + result['warning_text']
        for forbidden in REPUTATION_RISK_WORDS:
            self.assertNotIn(forbidden, combined)

    # ---- shared reputation-risk check across all five ----

    def test_no_reputation_risk_wording_in_any_split_pattern(self):
        cases = [
            {5: 100, 1: 80, 4: 60, 3: 40, 2: 20},   # x1xxx
            {5: 100, 4: 80, 1: 60, 2: 40, 3: 20},   # xx1xx
            {4: 100, 5: 80, 2: 60, 1: 40, 3: 20},   # xx213
            {5: 100, 3: 80, 4: 60, 2: 40, 1: 20},   # x3xxx
            {1: 100, 5: 80, 4: 60, 3: 40, 2: 20},   # 1xxxx
        ]
        for rating_dist in cases:
            with self.subTest(rating_dist=rating_dist):
                result = self._analyze(rating_dist)
                combined = result['advice_text'] + result['warning_text']
                for forbidden in REPUTATION_RISK_WORDS:
                    self.assertNotIn(forbidden, combined)


if __name__ == '__main__':
    unittest.main()
