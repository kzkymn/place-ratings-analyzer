#!/usr/bin/env python3
"""
Verifies that the user-facing texts formerly hardcoded in rating_analyzer.py
(template_notice/general_disclaimer etc.) are loaded from the external data file
(data/rating_messages.json).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer, QualityLevel


class TestRatingMessagesExternalized(unittest.TestCase):
    """Verify the texts are loaded from the external JSON file"""

    def setUp(self):
        self.pattern_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data', 'rating_patterns.csv'
        )

    def _make_temp_messages_file(self, messages: dict) -> str:
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json', encoding='utf-8'
        )
        json.dump(messages, temp_file, ensure_ascii=False)
        temp_file.close()
        return temp_file.name

    def test_custom_messages_file_overrides_template_notice_and_disclaimer(self):
        """The JSON given via messages_file is reflected in template_notice/general_disclaimer"""
        messages_path = self._make_temp_messages_file({
            'template_notice': 'センチネルテンプレート通知',
            'general_disclaimer': 'センチネル一般注意書き',
            'empty_advice_text': 'センチネル空データ',
            'unknown_advice_text': 'センチネル未知パターン({pattern})',
            'unknown_warning_text': 'センチネル未知警告',
        })
        try:
            analyzer = RuleBasedRatingAnalyzer(self.pattern_file, messages_file=messages_path)
            result = analyzer.analyze_distribution({5: 10, 4: 8, 3: 6, 2: 4, 1: 2})

            self.assertEqual(result['template_notice'], 'センチネルテンプレート通知')
            self.assertEqual(result['general_disclaimer'], 'センチネル一般注意書き')
        finally:
            os.unlink(messages_path)

    def test_custom_messages_file_overrides_empty_distribution_text(self):
        """messages_file texts are used even with an empty rating_dist"""
        messages_path = self._make_temp_messages_file({
            'template_notice': 'T',
            'general_disclaimer': 'D',
            'empty_advice_text': 'センチネル空データ',
            'unknown_advice_text': 'X({pattern})',
            'unknown_warning_text': 'W',
        })
        try:
            analyzer = RuleBasedRatingAnalyzer(self.pattern_file, messages_file=messages_path)
            result = analyzer.analyze_distribution({})

            self.assertEqual(result['advice_text'], 'センチネル空データ')
            self.assertEqual(result['template_notice'], 'T')
            self.assertEqual(result['general_disclaimer'], 'D')
        finally:
            os.unlink(messages_path)

    def test_custom_messages_file_overrides_unknown_pattern_text(self):
        """messages_file's unknown_advice_text/unknown_warning_text are used for unknown patterns"""
        messages_path = self._make_temp_messages_file({
            'template_notice': 'T',
            'general_disclaimer': 'D',
            'empty_advice_text': 'E',
            'unknown_advice_text': 'センチネル未知パターン({pattern})',
            'unknown_warning_text': 'センチネル未知警告',
        })
        try:
            analyzer = RuleBasedRatingAnalyzer(self.pattern_file, messages_file=messages_path)
            # A 6-grade rating matches no 5-digit wildcard, so the pattern is unknown
            rating_dist = {2: 10, 3: 8, 1: 6, 5: 4, 4: 2, 6: 1}
            result = analyzer.analyze_distribution(rating_dist)

            self.assertIn('センチネル未知パターン', result['advice_text'])
            self.assertEqual(result['warning_text'], 'センチネル未知警告')
        finally:
            os.unlink(messages_path)

    def test_default_messages_file_is_data_rating_messages_json(self):
        """Without messages_file, data/rating_messages.json is loaded by default"""
        analyzer = RuleBasedRatingAnalyzer(self.pattern_file)
        result = analyzer.analyze_distribution({5: 10, 4: 8, 3: 6, 2: 4, 1: 2})

        self.assertIn('template_notice', result)
        self.assertIn('general_disclaimer', result)
        self.assertIn('テンプレート', result['template_notice'])
        self.assertIn('比率', result['general_disclaimer'])

    def test_user_facing_messages_do_not_contain_internal_identifiers(self):
        """The common notice texts themselves contain no internal field/column names
        or English label values.

        Background: the tool description forbids the LLM from exposing any field
        names to the user, while also instructing it to relay template_notice /
        general_disclaimer in full. If field names appear inside those notice
        texts, the instructions contradict each other and the LLM chooses to copy
        the text verbatim (`quality_level: misc` etc. actually leaked into
        user-facing answers). Removing identifiers from the texts dissolves the
        contradiction itself."""
        analyzer = RuleBasedRatingAnalyzer(self.pattern_file)
        result = analyzer.analyze_distribution({5: 10, 4: 8, 3: 6, 2: 4, 1: 2})

        identifiers = [
            'quality_level', 'advice_text', 'warning_text', 'rating_distribution',
            'template_notice', 'general_disclaimer', 'confidence',
            'best_of_best', 'case_by_case', 'misc',
        ]
        for key in ('template_notice', 'general_disclaimer'):
            for identifier in identifiers:
                self.assertNotIn(
                    identifier, result[key],
                    f"{key} に内部識別子 '{identifier}' が含まれている"
                )

    def test_quality_level_constant_still_exported(self):
        """The centralized QualityLevel constants are still in place (regression check)"""
        self.assertEqual(QualityLevel.BEST_OF_BEST, 'best_of_best')


if __name__ == '__main__':
    unittest.main()
