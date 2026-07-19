#!/usr/bin/env python3
"""
Comprehensive test for all rating patterns in rating_patterns.csv
Tests all defined patterns and their advice outputs
Extensible design for future pattern additions
"""
import unittest
import csv
import sys
import os
from io import StringIO
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rating_analyzer import RuleBasedRatingAnalyzer


class TestRatingPatternsComprehensive(unittest.TestCase):
    """
    Comprehensive test suite for all rating patterns
    Automatically tests all patterns defined in rating_patterns.csv
    """
    
    def setUp(self):
        """Setup test environment"""
        self.pattern_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data/rating_patterns.csv'
        )
        self.analyzer = RuleBasedRatingAnalyzer(self.pattern_file)
        
        # Load all patterns from CSV for dynamic testing
        self.all_patterns = self._load_all_patterns()
    
    def _load_all_patterns(self):
        """Load all patterns from CSV file for dynamic testing"""
        patterns = {}
        with open(self.pattern_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                patterns[row['pattern']] = row
        return patterns
    
    def _create_rating_distribution_from_pattern(self, pattern):
        """
        Create a rating distribution that would generate the given pattern
        
        Args:
            pattern: Pattern string like "54321" or "45312"
            
        Returns:
            Dict mapping rating to count that produces the pattern
        """
        # Create base counts with the pattern order
        base_counts = [100, 80, 60, 40, 20]  # Descending counts
        rating_dist = {}
        
        for i, rating_char in enumerate(pattern):
            rating_num = int(rating_char)
            rating_dist[rating_num] = base_counts[i]
        
        return rating_dist
    
    def test_all_defined_patterns(self):
        """
        Test all patterns defined in rating_patterns.csv
        Dynamically discovers and tests each pattern
        """
        print(f"\n🔍 Testing {len(self.all_patterns)} defined patterns:")
        
        for pattern, expected_data in self.all_patterns.items():
            with self.subTest(pattern=pattern):
                # Skip wildcard patterns (contain 'x')
                if 'x' in pattern:
                    print(f"  ⏭️  Skipping wildcard pattern: {pattern}")
                    continue
                
                # Create test distribution
                rating_dist = self._create_rating_distribution_from_pattern(pattern)
                
                # Analyze the distribution
                result = self.analyzer.analyze_distribution(rating_dist)
                
                # Verify pattern recognition
                self.assertEqual(
                    result['pattern'], pattern,
                    f"Pattern {pattern}: Expected pattern {pattern}, got {result['pattern']}"
                )
                
                # Verify expected attributes
                self.assertEqual(
                    result['quality_level'], expected_data['quality_level'],
                    f"Pattern {pattern}: Quality level mismatch"
                )
                
                self.assertEqual(
                    result['advice_text'], expected_data['advice_text'],
                    f"Pattern {pattern}: Advice text mismatch"
                )
                
                self.assertEqual(
                    result['warning_text'], expected_data['warning_text'],
                    f"Pattern {pattern}: Warning text mismatch"
                )
                
                self.assertEqual(
                    result['confidence'], expected_data['confidence'],
                    f"Pattern {pattern}: Confidence level mismatch"
                )
                
                print(f"  ✅ {pattern}: {expected_data['quality_level']} - {expected_data['confidence']}")
    
    
    
    def test_pattern_coverage_statistics(self):
        """
        Generate statistics about pattern coverage and distribution
        Useful for understanding test completeness
        """
        print(f"\n📊 Pattern Coverage Statistics:")
        
        quality_levels = {}
        confidence_levels = {}
        
        for pattern, data in self.all_patterns.items():
            # Count quality levels
            quality = data['quality_level']
            quality_levels[quality] = quality_levels.get(quality, 0) + 1
            
            # Count confidence levels
            confidence = data['confidence']
            confidence_levels[confidence] = confidence_levels.get(confidence, 0) + 1
        
        print(f"  🏷️  Quality Levels: {quality_levels}")
        print(f"  🎯 Confidence Levels: {confidence_levels}")
        print(f"  📈 Total Patterns: {len(self.all_patterns)}")
        
        # Verify we have good coverage
        self.assertGreaterEqual(len(quality_levels), 3, "Should have at least 3 quality levels")
        self.assertGreaterEqual(len(confidence_levels), 2, "Should have at least 2 confidence levels")
    
    def test_console_output_for_all_patterns(self):
        """
        Test console output formatting for all patterns
        Ensures consistent output format across all patterns
        """
        print(f"\n🖥️  Testing console output format for all patterns:")
        
        for pattern, expected_data in self.all_patterns.items():
            if 'x' in pattern:  # Skip wildcard patterns
                continue
                
            with self.subTest(pattern=pattern):
                # Create test distribution
                rating_dist = self._create_rating_distribution_from_pattern(pattern)
                result = self.analyzer.analyze_distribution(rating_dist)
                
                # Test that all required fields are present for console output
                required_fields = [
                    'pattern', 'quality_level', 'advice_text', 'warning_text', 'confidence',
                    'template_notice', 'general_disclaimer'
                ]
                
                for field in required_fields:
                    self.assertIn(field, result, f"Pattern {pattern}: Missing field {field}")
                    self.assertIsNotNone(result[field], f"Pattern {pattern}: Field {field} is None")
                
                # Test output format (simulating console output)
                output_parts = [
                    f"📊 評価分布分析: {result['quality_level'].upper()}",
                    f"💡 アドバイス: {result['advice_text']}",
                    f"🎯 信頼度: {result['confidence']}"
                ]
                
                if result['warning_text']:
                    output_parts.insert(-1, f"⚠️ 注意点: {result['warning_text']}")
                
                console_output = '\n'.join(output_parts)
                
                # Verify output contains expected elements
                self.assertIn('📊', console_output)
                self.assertIn('💡', console_output)
                self.assertIn('🎯', console_output)
                
                print(f"  ✅ {pattern}: Console format OK")

    def test_disclaimers_consistent_across_all_patterns(self):
        """
        Verify template_notice/general_disclaimer come back as the same fixed texts
        for every pattern (regardless of quality_level). Guarantees the notices are
        never dropped or changed based on a label like best_of_best.
        """
        disclaimers = set()
        template_notices = set()

        for pattern in self.all_patterns:
            if 'x' in pattern:
                continue

            rating_dist = self._create_rating_distribution_from_pattern(pattern)
            result = self.analyzer.analyze_distribution(rating_dist)

            self.assertIn('general_disclaimer', result)
            self.assertIn('template_notice', result)
            disclaimers.add(result['general_disclaimer'])
            template_notices.add(result['template_notice'])

        self.assertEqual(len(disclaimers), 1, "general_disclaimerは全patternで同一であるべき")
        self.assertEqual(len(template_notices), 1, "template_noticeは全patternで同一であるべき")


if __name__ == '__main__':
    # Run with verbose output to see pattern testing details
    unittest.main(verbosity=2)