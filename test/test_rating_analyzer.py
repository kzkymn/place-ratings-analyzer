#!/usr/bin/env python3
"""
Test suite for RuleBasedRatingAnalyzer
Following TDD principles: Write failing tests first, then implement
"""
import unittest
import tempfile
import os
import csv
from unittest.mock import patch, mock_open
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer


class TestRuleBasedRatingAnalyzer(unittest.TestCase):
    
    def setUp(self):
        """Setup test data"""
        self.test_csv_content = """pattern,rank_1,rank_2,rank_3,rank_4,rank_5,quality_level,advice_text,warning_text,confidence,notes
54321,5,4,3,2,1,best_of_best,最高クラスの店舗,,high,test
45321,4,5,3,2,1,best,優良店,4突出注意,high,test"""
        
        # Create temporary CSV file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        self.temp_file.write(self.test_csv_content)
        self.temp_file.close()
        
    def tearDown(self):
        """Cleanup"""
        os.unlink(self.temp_file.name)
    
    def test_init_loads_patterns(self):
        """Test that initializer loads patterns correctly"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        self.assertIn('54321', analyzer.patterns)
        self.assertIn('45321', analyzer.patterns)
    
    def test_get_pattern_key_54321(self):
        """Test pattern key generation for 54321 pattern"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 10, 4: 8, 3: 5, 2: 3, 1: 2}
        pattern = analyzer._get_pattern_key(rating_dist)
        self.assertEqual(pattern, '54321')
    
    def test_get_pattern_key_45321(self):
        """Test pattern key generation for 45321 pattern"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 8, 4: 10, 3: 5, 2: 3, 1: 2}
        pattern = analyzer._get_pattern_key(rating_dist)
        self.assertEqual(pattern, '45321')
    
    def test_analyze_distribution_best_of_best(self):
        """Test analysis for best_of_best pattern"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 10, 4: 8, 3: 5, 2: 3, 1: 2}
        result = analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], '54321')
        self.assertEqual(result['quality_level'], 'best_of_best')
        self.assertIn('最高クラス', result['advice_text'])
        self.assertEqual(result['confidence'], 'high')
    
    def test_analyze_distribution_unknown_pattern(self):
        """Test analysis for unknown pattern"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 2, 4: 3, 3: 8, 2: 5, 1: 1}  # 32451 pattern
        result = analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], '32451')
        self.assertEqual(result['quality_level'], 'unknown')
        self.assertIn('パターンが見つかりません', result['advice_text'])
        self.assertEqual(result['confidence'], 'low')
    
    def test_analyze_distribution_empty_data(self):
        """Test analysis with empty rating distribution"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {}
        result = analyzer.analyze_distribution(rating_dist)

        self.assertEqual(result['quality_level'], 'unknown')
        self.assertIn('評価データが不足', result['advice_text'])

    def test_analyze_distribution_includes_template_notice(self):
        """The notice that advice_text/warning_text are template texts is always included"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 10, 4: 8, 3: 5, 2: 3, 1: 2}
        result = analyzer.analyze_distribution(rating_dist)

        self.assertIn('template_notice', result)
        self.assertIn('テンプレート', result['template_notice'])

    def test_analyze_distribution_includes_general_disclaimer(self):
        """The disclaimer that rank patterns alone cannot detect absolute-count anomalies is always included"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 10, 4: 8, 3: 5, 2: 3, 1: 2}
        result = analyzer.analyze_distribution(rating_dist)

        self.assertIn('general_disclaimer', result)
        # Carries the post-correction intent: look for absolute-count/ratio anomalies, not distribution shape
        self.assertIn('比率', result['general_disclaimer'])
        # Must not contain the misleading "fakes a natural-looking distribution" phrasing
        self.assertNotIn('自然に見える分布を', result['general_disclaimer'])
        # Must not imply the star5-dominance concern is peer-relative: the underlying
        # check (_check_star5_dominance) uses an absolute threshold by design, so an
        # entire category (e.g. high-end omakase sushi) can legitimately be flagged in
        # full - see cross-session memory project_rating_patterns_advice_warning_review
        # for the 2026-07-19 Shinjuku sushi case this guards against.
        self.assertNotIn('同業他店', result['general_disclaimer'])

    def test_disclaimers_are_identical_across_quality_levels(self):
        """The notices (template_notice/general_disclaimer) are identical across quality_levels"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)

        best_of_best_result = analyzer.analyze_distribution({5: 10, 4: 8, 3: 5, 2: 3, 1: 2})
        unknown_result = analyzer.analyze_distribution({5: 2, 4: 3, 3: 8, 2: 5, 1: 1})

        self.assertEqual(best_of_best_result['general_disclaimer'], unknown_result['general_disclaimer'])
        self.assertEqual(best_of_best_result['template_notice'], unknown_result['template_notice'])

    def test_analyze_distribution_empty_data_includes_disclaimers(self):
        """template_notice/general_disclaimer are returned even with empty rating data"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        result = analyzer.analyze_distribution({})

        self.assertIn('template_notice', result)
        self.assertIn('general_disclaimer', result)

    def test_load_patterns_file_not_found(self):
        """Test handling of missing pattern file"""
        with self.assertRaises(FileNotFoundError):
            RuleBasedRatingAnalyzer('nonexistent.csv')
    
    def test_get_pattern_key_equal_counts(self):
        """Test pattern key when multiple ratings have equal counts"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        rating_dist = {5: 5, 4: 5, 3: 5, 2: 5, 1: 5}
        pattern = analyzer._get_pattern_key(rating_dist)
        # Should handle ties consistently (by rating value descending)
        self.assertEqual(pattern, '54321')
    
    def test_integration_with_pipeline_data(self):
        """Test integration with typical pipeline data format"""
        analyzer = RuleBasedRatingAnalyzer(self.temp_file.name)
        # Simulate real rating distribution from pipeline
        pipeline_rating_dist = {1: 2, 2: 3, 3: 5, 4: 8, 5: 10}
        result = analyzer.analyze_distribution(pipeline_rating_dist)
        
        self.assertEqual(result['pattern'], '54321')
        self.assertEqual(result['quality_level'], 'best_of_best')
        self.assertIn('最高クラス', result['advice_text'])
    
    def test_case_by_case_pattern_54312(self):
        """Test case_by_case pattern 54312"""
        # Add case_by_case pattern to test data
        extended_csv = self.test_csv_content + '\n54312,5,4,3,1,2,case_by_case,5と4が多い優良店,店主キャラ注意,medium,test'
        
        temp_file2 = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        temp_file2.write(extended_csv)
        temp_file2.close()
        
        try:
            analyzer = RuleBasedRatingAnalyzer(temp_file2.name)
            rating_dist = {5: 10, 4: 8, 3: 5, 1: 3, 2: 2}  # 54312 pattern
            result = analyzer.analyze_distribution(rating_dist)
            
            self.assertEqual(result['pattern'], '54312')
            self.assertEqual(result['quality_level'], 'case_by_case')
            self.assertIn('優良店', result['advice_text'])
            self.assertEqual(result['confidence'], 'medium')
        finally:
            os.unlink(temp_file2.name)

if __name__ == '__main__':
    # Run with: python test/test_rating_analyzer.py
    unittest.main()