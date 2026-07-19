#!/usr/bin/env python3
"""
Test suite for the star5-dominance notice.

Detects distributions where star5 is disproportionately high - a signal that
can indicate review manipulation (incentivized/coerced reviews) that a
percentage-only "mixed ratings" check misses, since the manipulation may not
push the ratio to an extreme (see cross-session memory
project_rating_advice_llm_wording_fixes for the empirical basis of the
thresholds: ratio > 80%, or ratio >= 65% with a star5 count > 500).

This is deliberately independent of quality_level/pattern matching - it must
fire regardless of which CSV row the distribution happens to match, the same
way general_disclaimer is attached unconditionally.
"""
import unittest
import tempfile
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer


class TestStar5DominanceCheck(unittest.TestCase):

    def setUp(self):
        self.test_csv_content = """pattern,rank_1,rank_2,rank_3,rank_4,rank_5,quality_level,advice_text,warning_text,confidence,notes
54321,5,4,3,2,1,best_of_best,最高クラスの店舗,,high,test
xxxxx,x,x,x,x,x,misc,あまり見られないパターンです,,,test"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        self.temp_file.write(self.test_csv_content)
        self.temp_file.close()

    def tearDown(self):
        os.unlink(self.temp_file.name)

    def _analyzer(self):
        return RuleBasedRatingAnalyzer(self.temp_file.name)

    def test_notice_fires_when_ratio_exceeds_high_threshold(self):
        """Notice fires when star5 ratio exceeds 80% (e.g. 92.2%)"""
        analyzer = self._analyzer()
        rating_dist = {5: 1374, 4: 63, 3: 22, 2: 11, 1: 21}
        result = analyzer.analyze_distribution(rating_dist)
        self.assertIsNotNone(result['star5_dominance_notice'])

    def test_notice_fires_when_moderate_ratio_and_high_count(self):
        """Notice fires when ratio >= 65% and count > 500 (e.g. 66.3%, 1076)"""
        analyzer = self._analyzer()
        rating_dist = {5: 1076, 4: 381, 3: 116, 2: 23, 1: 28}
        result = analyzer.analyze_distribution(rating_dist)
        self.assertIsNotNone(result['star5_dominance_notice'])

    def test_notice_absent_when_ratio_high_but_count_low(self):
        """No notice when ratio >= 65% but count is below threshold (e.g. 75.9%, 343)"""
        analyzer = self._analyzer()
        rating_dist = {5: 343, 4: 69, 3: 32, 2: 2, 1: 6}
        result = analyzer.analyze_distribution(rating_dist)
        self.assertIsNone(result['star5_dominance_notice'])

    def test_notice_absent_when_ratio_below_moderate_threshold(self):
        """No notice when ratio is below 65%, regardless of count (e.g. 61.8%, 362)"""
        analyzer = self._analyzer()
        rating_dist = {5: 362, 4: 144, 3: 51, 2: 8, 1: 21}
        result = analyzer.analyze_distribution(rating_dist)
        self.assertIsNone(result['star5_dominance_notice'])

    def test_notice_absent_for_empty_distribution(self):
        """Empty distribution is handled without error and yields no notice"""
        analyzer = self._analyzer()
        result = analyzer.analyze_distribution({})
        self.assertIsNone(result['star5_dominance_notice'])

    def test_thresholds_are_configurable(self):
        """Thresholds can be overridden via the constructor"""
        analyzer = RuleBasedRatingAnalyzer(
            self.temp_file.name,
            star5_dominance_config={
                "high_ratio_percent": 50,
                "moderate_ratio_percent": 30,
                "moderate_count_threshold": 10,
            },
        )
        rating_dist = {5: 60, 4: 20, 3: 10, 2: 5, 1: 5}
        result = analyzer.analyze_distribution(rating_dist)
        self.assertIsNotNone(result['star5_dominance_notice'])

    def test_notice_text_does_not_assert_fraud(self):
        """Notice text avoids assertive/accusatory wording (reputation risk policy)"""
        analyzer = self._analyzer()
        rating_dist = {5: 1374, 4: 63, 3: 22, 2: 11, 1: 21}
        result = analyzer.analyze_distribution(rating_dist)
        notice = result['star5_dominance_notice']
        for forbidden in ('疑わし', 'サクラ', '不自然', '断定'):
            self.assertNotIn(forbidden, notice)

    def test_notice_text_instructs_separate_presentation(self):
        """Notice text carries the composition instruction: present the store
        individually, apart from the shared recommendation list.

        The same rule in the tool description alone was ignored in a real E2E
        run (2026-07-19: the flagged store appeared inside the recommendation
        table); the notice attached to the tool result is the text the client
        LLM demonstrably follows, so the positioning rule must live here.
        """
        analyzer = self._analyzer()
        rating_dist = {5: 1374, 4: 63, 3: 22, 2: 11, 1: 21}
        result = analyzer.analyze_distribution(rating_dist)
        notice = result['star5_dominance_notice']
        for required in ('一覧とは別に', '個別に'):
            self.assertIn(required, notice)


if __name__ == '__main__':
    unittest.main()
