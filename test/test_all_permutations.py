#!/usr/bin/env python3
"""
Test suite for all 120 permutations of rating patterns (1-5)
Verifies that CSV order priority works correctly for all possible combinations
"""
import unittest
import tempfile
import os
from itertools import permutations
from src.rating_analyzer import RuleBasedRatingAnalyzer


class TestAllPermutations(unittest.TestCase):
    """Test all 120 permutations of rating patterns"""
    
    def setUp(self):
        """Create temporary CSV file with priority order"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        
        # CSV with specific priority order to test
        csv_content = """pattern,quality_level,advice_text,warning_text,confidence
54321,best_of_best,Perfect order,Best pattern,high
45321,excellent,Great pattern,Good choice,high
xx321,good,Ends with 321,Wildcard match,medium
1xxxx,low_rating_dominant,Starts with 1,Avoid this,low"""
        
        self.temp_file.write(csv_content)
        self.temp_file.close()
    
    def tearDown(self):
        """Clean up temporary file"""
        os.unlink(self.temp_file.name)
    
    def test_all_120_permutations(self):
        """Test all 120 permutations of rating patterns (1-5)"""
        # Use actual CSV file instead of test file
        analyzer = RuleBasedRatingAnalyzer('data/rating_patterns.csv')
        
        # Generate all 120 permutations of [1,2,3,4,5]
        all_permutations = list(permutations([1, 2, 3, 4, 5]))
        self.assertEqual(len(all_permutations), 120, "Should have exactly 120 permutations")
        
        test_results = []
        
        for perm in all_permutations:
            # Create rating distribution from permutation (higher index = higher count)
            rating_dist = {}
            for i, rating in enumerate(perm):
                rating_dist[rating] = 100 - (i * 10)  # Decreasing counts
            
            result = analyzer.analyze_distribution(rating_dist)
            pattern = ''.join(map(str, perm))
            
            test_results.append({
                'permutation': pattern,
                'matched_pattern': result['pattern'],
                'quality_level': result['quality_level']
            })
        
        # Count matches by actual CSV patterns
        priority_matches = {
            '54321': 0,
            '45321': 0,
            '1xxxx': 0,
            'xx312': 0,
            'x3xxx': 0,
            'xx213': 0,
            'xx231': 0,
            'xx1xx': 0,
            'x1xxx': 0,
            'xx514': 0,
            'xx415': 0,
            'xx541': 0,
            'xx451': 0,
            'xxxxx': 0,
            'unknown': 0
        }
        
        for result in test_results:
            matched = result['matched_pattern']
            if matched in priority_matches:
                priority_matches[matched] += 1
            else:
                priority_matches['unknown'] += 1
        
        # Verify CSV priority order: 54321 should be matched exactly
        exact_54321_results = [r for r in test_results if r['permutation'] == '54321']
        self.assertEqual(len(exact_54321_results), 1)
        self.assertEqual(exact_54321_results[0]['matched_pattern'], '54321')
        
        # Verify 45321 should be matched exactly  
        exact_45321_results = [r for r in test_results if r['permutation'] == '45321']
        self.assertEqual(len(exact_45321_results), 1)
        self.assertEqual(exact_45321_results[0]['matched_pattern'], '45321')
        
        # Verify patterns starting with 1 match 1xxxx (high priority)
        starting_1_patterns = [r for r in test_results if r['permutation'].startswith('1')]
        for result in starting_1_patterns:
            self.assertEqual(result['matched_pattern'], '1xxxx',
                           f"Pattern {result['permutation']} should match 1xxxx (highest wildcard priority)")
            
        # Verify that xxxxx wildcard catches remaining patterns
        unmatched_by_specific = [r for r in test_results 
                               if not r['permutation'].startswith('1') 
                               and r['permutation'] not in ['54321', '45321']
                               and not any(r['matched_pattern'] == p for p in ['xx312', 'xx213', 'xx231', 'xx1xx', 'x1xxx', 'x3xxx', 'xx514', 'xx415', 'xx541', 'xx451'])]
        
        for result in unmatched_by_specific:
            self.assertEqual(result['matched_pattern'], 'xxxxx',
                           f"Pattern {result['permutation']} should match xxxxx fallback wildcard")
        
        
        
        # Verify all patterns are matched (no unknown patterns)
        self.assertEqual(priority_matches['unknown'], 0, "All 120 patterns should match defined CSV patterns")
    
if __name__ == '__main__':
    unittest.main()