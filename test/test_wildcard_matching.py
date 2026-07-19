#!/usr/bin/env python3
"""
TDD test suite for the wildcard-matching functionality
"""
import unittest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer, QualityLevel


class TestWildcardMatching(unittest.TestCase):
    """Test cases for wildcard matching"""
    
    def setUp(self):
        """Prepare the analyzer under test"""
        self.analyzer = RuleBasedRatingAnalyzer('data/rating_patterns.csv')
    
    def test_exact_pattern_matching(self):
        """Exact match of a fixed pattern"""
        rating_dist = {5: 10, 4: 8, 3: 6, 2: 4, 1: 2}
        result = self.analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], '54321')
        self.assertEqual(result['quality_level'], QualityLevel.BEST_OF_BEST)
    
    def test_wildcard_xx312_matching(self):
        """Wildcard matching for the xx312 pattern"""
        # 54312 pattern
        rating_dist = {5: 10, 4: 8, 3: 6, 1: 4, 2: 2}
        result = self.analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], 'xx312')
        self.assertEqual(result['quality_level'], QualityLevel.CASE_BY_CASE)

        # 45312 pattern
        rating_dist2 = {4: 10, 5: 8, 3: 6, 1: 4, 2: 2}
        result2 = self.analyzer.analyze_distribution(rating_dist2)

        self.assertEqual(result2['pattern'], 'xx312')
        self.assertEqual(result2['quality_level'], QualityLevel.CASE_BY_CASE)
    
    def test_wildcard_xx231_matching(self):
        """Wildcard matching for the xx231 pattern"""
        # 54231 pattern
        rating_dist = {5: 10, 4: 8, 2: 6, 3: 4, 1: 2}
        result = self.analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], 'xx231')
        self.assertEqual(result['quality_level'], QualityLevel.CASE_BY_CASE)
    
    def test_wildcard_x1xxx_matching(self):
        """Wildcard matching for the x1xxx pattern (1 in second place)"""
        # 51432 pattern
        rating_dist = {5: 10, 1: 8, 4: 6, 3: 4, 2: 2}
        result = self.analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], 'x1xxx')
        self.assertEqual(result['quality_level'], QualityLevel.REVIEW_CHECK_RECOMMENDED)
    
    def test_wildcard_1xxxx_matching(self):
        """Wildcard matching for the 1xxxx pattern (1 on top)"""
        # 15432 pattern
        rating_dist = {1: 10, 5: 8, 4: 6, 3: 4, 2: 2}
        result = self.analyzer.analyze_distribution(rating_dist)
        
        self.assertEqual(result['pattern'], '1xxxx')
        self.assertEqual(result['quality_level'], QualityLevel.LOW_RATING_DOMINANT)
    
    def test_unknown_pattern(self):
        """Unknown pattern"""
        # Use a longer (6-digit) pattern to guarantee it is undefined
        rating_dist = {2: 10, 3: 8, 1: 6, 5: 4, 4: 2, 6: 1}  # adding 6 forces a length mismatch
        result = self.analyzer.analyze_distribution(rating_dist)
        
        # 6 is an invalid rating, so the actual pattern becomes 231546, which matches no 5-digit wildcard
        self.assertEqual(result['quality_level'], QualityLevel.UNKNOWN)
        self.assertIn('未知のパターン', result['advice_text'])
    
    def test_matches_wildcard_pattern_method(self):
        """Unit test for _matches_wildcard_pattern()"""
        self.assertTrue(self.analyzer._matches_wildcard_pattern('54312', 'xx312'))
        self.assertTrue(self.analyzer._matches_wildcard_pattern('45312', 'xx312'))
        self.assertFalse(self.analyzer._matches_wildcard_pattern('54321', 'xx312'))
        self.assertTrue(self.analyzer._matches_wildcard_pattern('15432', '1xxxx'))
        self.assertFalse(self.analyzer._matches_wildcard_pattern('51432', '1xxxx'))
    
    def test_find_best_wildcard_match_method(self):
        """Unit test for _find_best_wildcard_match()"""
        patterns = self.analyzer.patterns
        
        # 54321 is a fixed pattern with top priority
        pattern, data = self.analyzer._find_best_wildcard_match('54321', patterns)
        self.assertEqual(pattern, '54321')
        
        # 54312 matches xx312
        pattern, data = self.analyzer._find_best_wildcard_match('54312', patterns)
        self.assertEqual(pattern, 'xx312')
        
        # 15432 matches 1xxxx (lower priority than x1xxx, but with 1 in first place 1xxxx is correct)
        pattern, data = self.analyzer._find_best_wildcard_match('15432', patterns)
        self.assertEqual(pattern, '1xxxx')


if __name__ == '__main__':
    unittest.main()