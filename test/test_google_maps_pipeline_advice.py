#!/usr/bin/env python3
"""
Integration tests for GoogleMapsPipeline with rating advice functionality
Tests the complete pipeline with advice analysis
"""
import unittest
import tempfile
import os
import csv
import json
from unittest.mock import patch, mock_open
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import GoogleMapsPipeline


class TestGoogleMapsPipelineAdvice(unittest.TestCase):
    
    def setUp(self):
        """Setup test environment"""
        # Create test CSV data with rating distribution
        self.test_csv_content = '''title,category,address,review_rating,review_count,reviews_per_rating,price_range,phone,website,emails
テスト寿司店,Japanese restaurant,東京都渋谷区,4.5,100,"{""1"": 2, ""2"": 3, ""3"": 5, ""4"": 8, ""5"": 10}",$$,03-1234-5678,https://example.com,test@example.com'''
        
        # Create temporary CSV file
        self.temp_csv = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        self.temp_csv.write(self.test_csv_content)
        self.temp_csv.close()
        
        # Create temporary pattern file
        self.pattern_csv_content = '''pattern,rank_1,rank_2,rank_3,rank_4,rank_5,quality_level,advice_text,warning_text,confidence,notes
54321,5,4,3,2,1,best_of_best,最高クラスの店舗です,信頼度の高い優良店です,high,test'''
        
        self.temp_pattern = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        self.temp_pattern.write(self.pattern_csv_content)
        self.temp_pattern.close()
    
    def tearDown(self):
        """Cleanup"""
        os.unlink(self.temp_csv.name)
        os.unlink(self.temp_pattern.name)
    
    @patch('src.pipeline.GoogleMapsPipeline.__init__')
    def test_analyze_results_with_advice(self, mock_init):
        """Test analyze_results method includes rating advice"""
        # Mock the initialization to use our test pattern file
        mock_init.return_value = None
        
        pipeline = GoogleMapsPipeline()
        pipeline.scraper_path = '/fake/path'
        
        # Initialize rating analyzer with test pattern file
        from src.rating_analyzer import RuleBasedRatingAnalyzer
        pipeline.rating_analyzer = RuleBasedRatingAnalyzer(self.temp_pattern.name)
        
        # Test analyze_results
        results = pipeline.analyze_results(self.temp_csv.name)
        
        self.assertEqual(results['total_places'], 1)
        place = results['places'][0]
        
        # Check basic data
        self.assertEqual(place['name'], 'テスト寿司店')
        self.assertEqual(place['rating'], 4.5)
        self.assertEqual(place['review_count'], 100)
        
        # Check rating distribution
        self.assertIsNotNone(place['rating_distribution'])
        self.assertEqual(place['rating_distribution']['star_5']['count'], 10)
        self.assertEqual(place['rating_distribution']['star_1']['count'], 2)
        
        # Check advice analysis
        self.assertIn('rating_advice', place)
        advice = place['rating_advice']
        self.assertEqual(advice['pattern'], '54321')
        self.assertEqual(advice['quality_level'], 'best_of_best')
        self.assertIn('最高クラス', advice['advice_text'])
        self.assertEqual(advice['confidence'], 'high')

        # The template notice / general disclaimer propagate into the final pipeline output
        self.assertIn('template_notice', advice)
        self.assertIn('general_disclaimer', advice)

    def test_empty_rating_distribution_handling(self):
        """Test handling of places without rating distribution"""
        # Create CSV without rating distribution
        csv_content = '''title,category,address,review_rating,review_count,price_range
テスト店,Restaurant,東京都,4.0,50,$'''
        
        temp_csv = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        temp_csv.write(csv_content)
        temp_csv.close()
        
        try:
            with patch('src.pipeline.GoogleMapsPipeline.__init__') as mock_init:
                mock_init.return_value = None
                
                pipeline = GoogleMapsPipeline()
                pipeline.scraper_path = '/fake/path'
                
                from src.rating_analyzer import RuleBasedRatingAnalyzer
                pipeline.rating_analyzer = RuleBasedRatingAnalyzer(self.temp_pattern.name)
                
                results = pipeline.analyze_results(temp_csv.name)
                place = results['places'][0]
                
                # Should not have rating_advice for places without distribution
                self.assertNotIn('rating_advice', place)
                
        finally:
            os.unlink(temp_csv.name)


if __name__ == '__main__':
    unittest.main()