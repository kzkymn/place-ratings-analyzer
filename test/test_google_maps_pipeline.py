#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps Pipeline test suite
Comprehensive tests following TDD principles
"""

import unittest
import contextlib
import io
import tempfile
import os
import json
import csv
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.pipeline import GoogleMapsPipeline


def _make_popen_mock(returncode=0, stdout_lines=None, stderr_lines=None):
    """Build a MagicMock standing in for subprocess.Popen's return value.

    .stdout/.stderr are plain iterators of lines (mirroring how a real Popen's
    text-mode pipe is iterated line by line), and .wait() returns returncode -
    matching extract_places()'s Popen + threaded-line-reader implementation.
    """
    mock_process = MagicMock()
    mock_process.stdout = iter(stdout_lines or [])
    mock_process.stderr = iter(stderr_lines or [])
    mock_process.wait.return_value = returncode
    return mock_process


class TestGoogleMapsPipeline(unittest.TestCase):
    """Tests for the GoogleMapsPipeline class"""

    def setUp(self):
        """Per-test preparation"""
        self.test_scraper_path = '/tmp/fake_scraper'
        # Create a mock scraper binary file
        with open(self.test_scraper_path, 'w') as f:
            f.write('#!/bin/bash\necho "mock scraper"')
        os.chmod(self.test_scraper_path, 0o755)
        
        self.pipeline = GoogleMapsPipeline(scraper_path=self.test_scraper_path)
    
    def tearDown(self):
        """Per-test cleanup"""
        if os.path.exists(self.test_scraper_path):
            os.unlink(self.test_scraper_path)
    
    def test_init_with_valid_scraper_path(self):
        """Initialization with a valid scraper path"""
        pipeline = GoogleMapsPipeline(scraper_path=self.test_scraper_path)
        self.assertEqual(pipeline.scraper_path, self.test_scraper_path)
    
    def test_init_with_invalid_scraper_path(self):
        """Initialization error with an invalid scraper path"""
        with self.assertRaises(FileNotFoundError):
            GoogleMapsPipeline(scraper_path='/non/existent/path')
    
    def test_parse_place_data_basic(self):
        """Basic place-data parsing"""
        row = {
            'title': 'Test Restaurant',
            'category': 'Restaurant',
            'address': 'Tokyo, Japan',
            'review_rating': '4.5',
            'review_count': '100',
            'price_range': '¥¥¥',
            'phone': '03-1234-5678',
            'website': 'https://test.com',
            'emails': 'test@test.com'
        }
        
        result = self.pipeline._parse_place_data(row, detailed_info=False)
        
        self.assertEqual(result['name'], 'Test Restaurant')
        self.assertEqual(result['category'], 'Restaurant') 
        self.assertEqual(result['address'], 'Tokyo, Japan')
        self.assertEqual(result['rating'], 4.5)
        self.assertEqual(result['review_count'], 100)
        self.assertEqual(result['price_range'], '¥¥¥')
        self.assertEqual(result['phone'], '03-1234-5678')
        self.assertEqual(result['website'], 'https://test.com')
        self.assertEqual(result['emails'], 'test@test.com')
    
    def test_parse_place_data_with_rating_distribution(self):
        """Per-star rating distribution parsing"""
        row = {
            'title': 'Test Restaurant',
            'category': 'Restaurant',
            'address': 'Tokyo, Japan',
            'review_rating': '4.5',
            'review_count': '100',
            'reviews_per_rating': '{"5": "50", "4": "30", "3": "15", "2": "3", "1": "2"}'
        }
        
        result = self.pipeline._parse_place_data(row, detailed_info=False)
        
        self.assertIsNotNone(result['rating_distribution'])
        self.assertEqual(result['rating_distribution']['star_5']['count'], 50)
        self.assertEqual(result['rating_distribution']['star_4']['count'], 30)
        self.assertIn('★5:', result['histogram_ascii'])
        self.assertIn('★4:', result['histogram_ascii'])
    
    def test_parse_place_data_with_business_hours(self):
        """Business-hours parsing"""
        hours_json = '{"Monday": ["9:00-17:00"], "Tuesday": ["9:00-17:00"]}'
        row = {
            'title': 'Test Restaurant',
            'category': 'Restaurant',
            'open_hours': hours_json
        }
        
        result = self.pipeline._parse_place_data(row, detailed_info=True)
        
        self.assertIsNotNone(result['business_hours'])
        self.assertIn('Monday', result['business_hours']['formatted'])
        self.assertIn('Tuesday', result['business_hours']['formatted'])
    
    def test_parse_place_data_with_sample_reviews(self):
        """Sample-review parsing"""
        reviews_json = '[{"Name": "Test User", "Rating": "5", "Description": "Great food!"}]'
        row = {
            'title': 'Test Restaurant',
            'category': 'Restaurant',
            'user_reviews_extended': reviews_json
        }
        
        result = self.pipeline._parse_place_data(row, detailed_info=True)
        
        self.assertIsNotNone(result['sample_reviews'])
        self.assertEqual(len(result['sample_reviews']), 1)
        self.assertEqual(result['sample_reviews'][0]['reviewer_name'], 'Test User')
        self.assertEqual(result['sample_reviews'][0]['rating'], '5')
        self.assertEqual(result['sample_reviews'][0]['description'], 'Great food!')
    
    def test_generate_summary_with_valid_data(self):
        """Summary generation with valid data"""
        places = [
            {'rating': 4.5, 'review_count': 100, 'name': 'Place A'},
            {'rating': 4.0, 'review_count': 50, 'name': 'Place B'},
            {'rating': None, 'review_count': 0, 'name': 'Place C'}
        ]
        
        summary = self.pipeline._generate_summary(places)
        
        self.assertEqual(summary['average_rating'], 4.25)
        self.assertEqual(summary['total_reviews'], 150)
        self.assertEqual(summary['places_with_rating'], 2)
        self.assertEqual(len(summary['top_rated_places']), 2)
        self.assertEqual(summary['top_rated_places'][0]['name'], 'Place A')
    
    def test_generate_summary_with_empty_data(self):
        """Summary generation with empty data"""
        summary = self.pipeline._generate_summary([])
        self.assertEqual(summary, {})
    
    def test_parse_business_hours_valid_json(self):
        """Business-hours parsing with valid JSON"""
        hours_json = '{"Monday": ["9:00-17:00"], "Tuesday": ["10:00-18:00"]}'
        result = self.pipeline._parse_business_hours(hours_json)
        
        self.assertIsNotNone(result['raw'])
        self.assertIn('Monday: 9:00-17:00', result['formatted'])
        self.assertIn('Tuesday: 10:00-18:00', result['formatted'])
    
    def test_parse_business_hours_invalid_json(self):
        """Business-hours parsing with invalid JSON"""
        invalid_json = 'Invalid JSON format'
        result = self.pipeline._parse_business_hours(invalid_json)
        
        self.assertIsNone(result['raw'])
        self.assertEqual(result['formatted'], invalid_json)
        self.assertIn('parse_error', result)
    
    def test_parse_sample_reviews_valid_json(self):
        """Review parsing with valid JSON"""
        reviews_json = '[{"Name": "User1", "Rating": "5", "Description": "' + "A" * 150 + '"}, {"Name": "User2", "Rating": "4", "Description": "Good"}]'
        result = self.pipeline._parse_sample_reviews(reviews_json)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['reviewer_name'], 'User1')
        self.assertEqual(len(result[0]['description']), 150)  # full text since the limit was removed
        self.assertEqual(result[1]['reviewer_name'], 'User2')
        self.assertEqual(result[1]['description'], 'Good')
    
    def test_parse_sample_reviews_invalid_json(self):
        """Review parsing with invalid JSON"""
        invalid_json = 'Invalid JSON'
        result = self.pipeline._parse_sample_reviews(invalid_json)
        
        self.assertEqual(len(result), 1)
        self.assertIn('parse_error', result[0])
    
    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extract_places_successful_execution(self, mock_popen):
        """Successful data extraction run"""
        mock_popen.return_value = _make_popen_mock(returncode=0)

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'):
                with patch('os.close'):
                    result = self.pipeline.extract_places('テストクエリ')

                    self.assertEqual(result, '/tmp/test.csv')
                    mock_popen.assert_called_once()
                    # Verify -lang ja is passed
                    call_args = mock_popen.call_args[0][0]
                    self.assertIn('-lang', call_args, "コマンドに-langが含まれること")
                    lang_idx = call_args.index('-lang')
                    self.assertEqual(call_args[lang_idx + 1], 'ja', "-lang jaが渡されること")

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extract_places_logs_scraper_stdout_even_on_success(self, mock_popen):
        """
        The Go scraper's own stdout/stderr must reach the diagnostic log even
        when it exits 0 - previously this was only surfaced on failure
        (returncode != 0), so a run that "succeeds" but silently finds
        nothing (e.g. the scraper itself printing a warning about a blocked
        request or an empty result page) left no trace anywhere, making a
        real production incident impossible to diagnose from logs alone.
        """
        mock_popen.return_value = _make_popen_mock(
            returncode=0,
            stdout_lines=['scraper diagnostic: 0 results for query\n'],
            stderr_lines=['some warning\n'],
        )

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'):
                with patch('os.close'):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.pipeline.extract_places('テストクエリ')

                    self.assertEqual('', stdout.getvalue(), "stdout must stay clean (MCP stdio transport)")
                    self.assertIn('scraper diagnostic: 0 results for query', stderr.getvalue())
                    self.assertIn('some warning', stderr.getvalue())

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extract_places_logs_output_line_by_line(self, mock_popen):
        """
        Each line of the scraper's output must be logged as its own _diag()
        call as it is read, not joined into one block after the process
        exits - a run that hangs partway through must leave a partial trail
        in the logs (which lines arrived, and when) instead of total silence
        until completion. This is what makes a future hang diagnosable.
        """
        mock_popen.return_value = _make_popen_mock(
            returncode=0,
            stderr_lines=['line one\n', 'line two\n', 'line three\n'],
        )

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'), patch('os.close'):
                with patch('src.pipeline._diag') as mock_diag:
                    self.pipeline.extract_places('テストクエリ')

        diag_messages = [call.args[0] for call in mock_diag.call_args_list]
        self.assertTrue(any('line one' in m for m in diag_messages))
        self.assertTrue(any('line two' in m for m in diag_messages))
        self.assertTrue(any('line three' in m for m in diag_messages))
        # each line must be its own call, not one joined dump
        self.assertFalse(
            any('line one' in m and 'line three' in m for m in diag_messages),
            "各行が個別にログされること（まとめて1回でログされてはならない）"
        )

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extract_places_scraper_failure(self, mock_popen):
        """Scraper execution failure"""
        mock_popen.return_value = _make_popen_mock(
            returncode=1, stderr_lines=['Go scraper failed with some error\n']
        )

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'):
                with patch('os.close'):
                    with self.assertRaisesRegex(RuntimeError, 'Go scraper failed: Go scraper failed with some error'):
                        self.pipeline.extract_places('テストクエリ')
                    mock_popen.assert_called_once()

    def test_analyze_results_with_valid_csv(self):
        """Analysis of a valid CSV file"""
        test_csv_content = '''title,category,address,review_rating,review_count,price_range,phone,website,emails
Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,https://test.com,test@test.com
Test Cafe,Cafe,Shibuya Japan,4.0,50,¥¥,03-5678-1234,https://cafe.com,cafe@cafe.com'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(test_csv_content)
            csv_path = f.name
        
        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)
            
            self.assertEqual(result['total_places'], 2)
            self.assertEqual(len(result['places']), 2)
            self.assertEqual(result['places'][0]['name'], 'Test Restaurant')
            self.assertEqual(result['places'][1]['name'], 'Test Cafe')
            self.assertIn('summary', result)
            
        finally:
            os.unlink(csv_path)

    def test_analyze_results_area_search_notice_present_for_multiple_places(self):
        """area+category-style searches (multiple hits) surface a notice
        pointing at mixed-ratings-workflow, so an LLM that skipped straight to
        a direct search (instead of the workflow) for an 'avoid store' request
        gets a chance to self-correct once it sees the result - the tool
        description's instruction alone was shown (2026-07-19 E2E) to be
        ignored at that decision point, and there is no per-store result yet
        for that decision to attach to the way star5_dominance_notice does."""
        test_csv_content = '''title,category,address,review_rating,review_count,price_range,phone,website,emails
Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,https://test.com,test@test.com
Test Cafe,Cafe,Shibuya Japan,4.0,50,¥¥,03-5678-1234,https://cafe.com,cafe@cafe.com'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(test_csv_content)
            csv_path = f.name

        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)
            self.assertIsNotNone(result['area_search_notice'])
            self.assertIn('mixed-ratings-workflow', result['area_search_notice'])
        finally:
            os.unlink(csv_path)

    def test_analyze_results_area_search_notice_absent_for_single_place(self):
        """A store-name search (exactly one hit) is not the biased-toward-
        famous-stores case the notice warns about, so it must not fire."""
        test_csv_content = '''title,category,address,review_rating,review_count,price_range,phone,website,emails
Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,https://test.com,test@test.com'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(test_csv_content)
            csv_path = f.name

        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)
            self.assertIsNone(result['area_search_notice'])
        finally:
            os.unlink(csv_path)

    def test_analyze_results_scrape_processing_error_notice_present_when_flagged(self):
        """When extract_places detected the scrapemate job-processing-error
        log line (see src/pipeline.py's extract_places), analyze_results must
        carry a notice warning that a low/zero result count may not be a
        genuine zero."""
        test_csv_content = '''title,category,address,review_rating,review_count,price_range,phone,website,emails
Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,https://test.com,test@test.com'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(test_csv_content)
            csv_path = f.name

        try:
            self.pipeline._last_extraction_had_job_error = True
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)
            self.assertIsNotNone(result['scrape_processing_error_notice'])
        finally:
            os.unlink(csv_path)

    def test_analyze_results_scrape_processing_error_notice_absent_by_default(self):
        """A clean run (no job-processing-error log line seen) must not carry
        the notice, and this must hold even before extract_places has ever
        run (attribute unset) - not just after a clean run sets it False."""
        test_csv_content = '''title,category,address,review_rating,review_count,price_range,phone,website,emails
Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,https://test.com,test@test.com'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(test_csv_content)
            csv_path = f.name

        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)
            self.assertIsNone(result['scrape_processing_error_notice'])
        finally:
            os.unlink(csv_path)

    def test_analyze_results_file_not_found(self):
        """Analysis error for a nonexistent CSV file"""
        with self.assertRaises(FileNotFoundError):
            self.pipeline.analyze_results('/non/existent/file.csv')
    
    @patch.object(GoogleMapsPipeline, 'extract_places')
    @patch.object(GoogleMapsPipeline, 'analyze_results')
    def test_run_pipeline_integration(self, mock_analyze, mock_extract):
        """End-to-end pipeline integration"""
        mock_extract.return_value = '/tmp/test.csv'
        mock_analyze.return_value = {
            'total_places': 1,
            'places': [{'name': 'Test Place'}],
            'summary': {'average_rating': 4.5}
        }
        
        with patch.object(self.pipeline, '_print_console_output'):
            result = self.pipeline.run_pipeline('テストクエリ')
            
            self.assertEqual(result['total_places'], 1)
            mock_extract.assert_called_once_with('テストクエリ')
            mock_analyze.assert_called_once_with('/tmp/test.csv', detailed_info=True)

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extra_reviews_not_in_subprocess_command_by_default(self, mock_popen):
        """-extra-reviews is not in the subprocess command by default"""
        mock_popen.return_value = _make_popen_mock(returncode=0)

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'), patch('os.close'):
                self.pipeline.extract_places('テストクエリ')

        call_args = mock_popen.call_args[0][0]
        self.assertNotIn('-extra-reviews', call_args,
                         "-extra-reviewsはデフォルトでコマンドに含まれてはならない")

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_extra_reviews_never_in_subprocess_command_even_if_true(self, mock_popen):
        """-extra-reviews is not in the command even with extra_reviews=True (disabled)"""
        mock_popen.return_value = _make_popen_mock(returncode=0)

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'), patch('os.close'):
                self.pipeline.extract_places('テストクエリ', extra_reviews=True)

        call_args = mock_popen.call_args[0][0]
        self.assertNotIn('-extra-reviews', call_args,
                         "-extra-reviewsは無効化されているためTrueでもコマンドに含まれてはならない")

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.Popen')
    def test_concurrency_forced_to_one_for_histogram_data(self, mock_popen):
        """concurrency is always pinned to 1 for rating-distribution retrieval
        (at high parallelism Google serves lite pages and the distribution goes missing)"""
        mock_popen.return_value = _make_popen_mock(returncode=0)

        with patch('tempfile.mkstemp') as mock_temp:
            mock_temp.return_value = (1, '/tmp/test.csv')
            with patch('os.fdopen'), patch('os.close'):
                self.pipeline.extract_places('テストクエリ', concurrency=8)

        call_args = mock_popen.call_args[0][0]
        c_idx = call_args.index('-c')
        self.assertEqual(call_args[c_idx + 1], '1',
                         "評価分布取得のため-c は常に1でなければならない")

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    def test_extract_places_streams_real_subprocess_output_before_exit(self):
        """
        Integration test with a REAL subprocess (per project convention: a
        function that shells out must be covered by a real-binary test, not
        mocks alone). A script that sleeps between two prints must have its
        first line reach the log well before the sleep completes - proving
        output is drained live, not buffered until the process exits.

        A mocked Popen cannot prove this: the mock has no wall-clock
        relationship between "the process is still running" and "a line was
        logged". That relationship is exactly the property production was
        missing (a hang produced zero log lines until the process finally
        exited 60+ seconds later).
        """
        slow_script = '/tmp/slow_diag_scraper.sh'
        with open(slow_script, 'w') as f:
            f.write(
                '#!/bin/bash\n'
                'echo "first line" >&2\n'
                'sleep 1.5\n'
                'echo "second line" >&2\n'
            )
        os.chmod(slow_script, 0o755)
        pipeline = GoogleMapsPipeline(scraper_path=slow_script)

        try:
            first_line_time = []
            start_time = time.time()

            def _spying_diag(message):
                if 'first line' in message and not first_line_time:
                    first_line_time.append(time.time())

            with patch('src.pipeline._diag', side_effect=_spying_diag):
                pipeline.extract_places('テストクエリ', output_file='/tmp/slow_test.csv')

            self.assertEqual(len(first_line_time), 1, "最初の行が一度だけログされること")
            elapsed_to_first_line = first_line_time[0] - start_time
            # The script sleeps 1.5s between the two lines. If "first line"
            # is only visible after the whole process (sleep included) has
            # finished, elapsed would be >= 1.5s. Real-time draining must
            # surface it almost immediately - well under the sleep duration.
            self.assertLess(
                elapsed_to_first_line, 1.0,
                f"最初の行はsleep完了({elapsed_to_first_line:.2f}秒)より十分前にログされるべき"
                "（バッファされてプロセス終了後にまとめて出ているならこの検証は失敗する）"
            )
        finally:
            if os.path.exists(slow_script):
                os.unlink(slow_script)
            if os.path.exists('/tmp/slow_test.csv'):
                os.unlink('/tmp/slow_test.csv')


class TestEdgeCases(unittest.TestCase):
    """Edge-case tests"""
    
    def setUp(self):
        self.test_scraper_path = '/tmp/fake_scraper'
        with open(self.test_scraper_path, 'w') as f:
            f.write('#!/bin/bash\necho "mock"')
        os.chmod(self.test_scraper_path, 0o755)
        self.pipeline = GoogleMapsPipeline(scraper_path=self.test_scraper_path)
    
    def tearDown(self):
        if os.path.exists(self.test_scraper_path):
            os.unlink(self.test_scraper_path)
    
    def test_parse_place_data_missing_fields(self):
        """Missing required fields"""
        row = {}  # empty data
        
        result = self.pipeline._parse_place_data(row, detailed_info=False)
        
        self.assertEqual(result['name'], '')
        self.assertEqual(result['category'], '')
        self.assertEqual(result['address'], '')
        self.assertIsNone(result['rating'])
        self.assertEqual(result['review_count'], 0)
    
    def test_parse_place_data_invalid_rating(self):
        """Invalid rating values"""
        row = {
            'title': 'Test',
            'review_rating': 'invalid',
            'review_count': 'invalid'
        }
        
        result = self.pipeline._parse_place_data(row, detailed_info=False)
        
        self.assertIsNone(result['rating'])
        self.assertEqual(result['review_count'], 0)
    
    def test_rating_distribution_zero_total(self):
        """Rating distribution with a total review count of 0"""
        row = {
            'title': 'Test',
            'reviews_per_rating': '{"5": "0", "4": "0", "3": "0", "2": "0", "1": "0"}'
        }

        result = self.pipeline._parse_place_data(row, detailed_info=False)

        self.assertIsNone(result['rating_distribution'])
        self.assertIsNone(result['histogram_ascii'])

    def test_data_incomplete_flag_set_when_review_count_zero_and_no_distribution(self):
        """data_incomplete flag is set when review_count=0 and rating_distribution=None"""
        row = {'title': 'テスト店舗', 'review_rating': '4.7', 'review_count': '0'}

        result = self.pipeline._parse_place_data(row, detailed_info=False)

        self.assertTrue(result.get('data_incomplete'),
                        "review_count=0かつ分布なしのとき data_incomplete=True になること")
        self.assertIn('data_incomplete_hint', result,
                      "data_incomplete_hint フィールドが存在すること")
        self.assertIn('テスト店舗', result['data_incomplete_hint'],
                      "ヒントに店名が含まれること（直接検索用）")

    def test_data_incomplete_flag_not_set_when_review_count_nonzero(self):
        """data_incomplete flag is not set when review_count>0"""
        row = {
            'title': 'テスト店舗',
            'review_rating': '4.5',
            'review_count': '100',
            'reviews_per_rating': '{"5":"50","4":"30","3":"15","2":"3","1":"2"}'
        }

        result = self.pipeline._parse_place_data(row, detailed_info=False)

        self.assertFalse(result.get('data_incomplete', False),
                         "review_count>0のとき data_incomplete=False になること")


class TestPrintOutput(unittest.TestCase):
    """Console output tests"""
    
    def setUp(self):
        self.test_scraper_path = '/tmp/fake_scraper'
        with open(self.test_scraper_path, 'w') as f:
            f.write('#!/bin/bash\necho "mock"')
        os.chmod(self.test_scraper_path, 0o755)
        self.pipeline = GoogleMapsPipeline(scraper_path=self.test_scraper_path)
    
    def tearDown(self):
        if os.path.exists(self.test_scraper_path):
            os.unlink(self.test_scraper_path)
    
    @patch('builtins.print')
    def test_print_console_output_basic(self, mock_print):
        """Basic console output"""
        results = {
            'total_places': 2,
            'places': [
                {
                    'name': 'Test Restaurant',
                    'category': 'Restaurant',
                    'address': 'Tokyo, Japan',
                    'rating': 4.5,
                    'review_count': 100,
                    'price_range': '¥¥¥',
                    'phone': '03-1234-5678',
                    'website': 'https://test.com',
                    'emails': 'test@test.com'
                }
            ]
        }
        
        self.pipeline._print_console_output(results)
        self.assertTrue(mock_print.called)
    
    @patch('builtins.print')
    def test_print_console_output_with_business_hours(self, mock_print):
        """Console output with business hours"""
        results = {
            'total_places': 1,
            'places': [
                {
                    'name': 'Test Restaurant',
                    'category': 'Restaurant',
                    'address': 'Tokyo, Japan',
                    'rating': 4.5,
                    'review_count': 100,
                    'price_range': '¥¥¥',
                    'phone': '03-1234-5678',
                    'website': 'https://test.com',
                    'emails': 'test@test.com',
                    'business_hours': {
                        'formatted': 'Monday: 9:00-17:00\nTuesday: 9:00-17:00'
                    }
                }
            ]
        }
        
        self.pipeline._print_console_output(results)
        self.assertTrue(mock_print.called)
    
    @patch('builtins.print')
    def test_print_console_output_with_histogram(self, mock_print):
        """Console output with a histogram"""
        results = {
            'total_places': 1,
            'places': [
                {
                    'name': 'Test Restaurant',
                    'category': 'Restaurant', 
                    'address': 'Tokyo, Japan',
                    'rating': 4.5,
                    'review_count': 100,
                    'price_range': '¥¥¥',
                    'phone': '03-1234-5678',
                    'website': 'https://test.com',
                    'emails': 'test@test.com',
                    'histogram_ascii': '★5: 50件 (50.0%) ██████████\n★4: 30件 (30.0%) ██████'
                }
            ]
        }
        
        self.pipeline._print_console_output(results)
        self.assertTrue(mock_print.called)
    
    @patch('builtins.print') 
    def test_print_console_output_with_sample_reviews(self, mock_print):
        """Console output with sample reviews"""
        results = {
            'total_places': 1,
            'places': [
                {
                    'name': 'Test Restaurant',
                    'category': 'Restaurant',
                    'address': 'Tokyo, Japan', 
                    'rating': 4.5,
                    'review_count': 100,
                    'price_range': '¥¥¥',
                    'phone': '03-1234-5678',
                    'website': 'https://test.com',
                    'emails': 'test@test.com',
                    'sample_reviews': [
                        {
                            'reviewer_name': 'Test User',
                            'rating': '5',
                            'description': 'Great food!'
                        }
                    ]
                }
            ]
        }
        
        self.pipeline._print_console_output(results)
        self.assertTrue(mock_print.called)
    
    @patch('builtins.print')
    def test_print_console_output_limit_to_3_places(self, mock_print):
        """Console output limited to 3 places"""
        places = []
        for i in range(5):
            places.append({
                'name': f'Restaurant {i+1}',
                'category': 'Restaurant',
                'address': f'Address {i+1}',
                'rating': 4.0 + i * 0.1,
                'review_count': 50 + i * 10,
                'price_range': '¥¥',
                'phone': f'03-1234-567{i}',
                'website': f'https://test{i}.com',
                'emails': f'test{i}@test.com',
                'sample_reviews': [{'reviewer_name': f'User{i}', 'rating': '4', 'description': 'Good'}]
            })
        
        results = {
            'total_places': 5,
            'places': places
        }
        
        self.pipeline._print_console_output(results)
        self.assertTrue(mock_print.called)

    @patch('builtins.print')
    def test_print_console_output_includes_general_disclaimer(self, mock_print):
        """When rating_advice is shown, general_disclaimer (the absolute-count/ratio anomaly notice) is printed"""
        results = {
            'total_places': 1,
            'places': [
                {
                    'name': 'Test Restaurant',
                    'category': 'Restaurant',
                    'address': 'Tokyo, Japan',
                    'rating': 4.5,
                    'review_count': 100,
                    'price_range': '¥¥¥',
                    'phone': '03-1234-5678',
                    'website': 'https://test.com',
                    'emails': 'test@test.com',
                    'rating_advice': {
                        'pattern': '54321',
                        'quality_level': 'best_of_best',
                        'advice_text': '最高クラスの店舗です',
                        'warning_text': '',
                        'confidence': 'high',
                        'template_notice': 'これはテンプレート文です',
                        'general_disclaimer': '同業他店と比較した比率の異常値を確認してください'
                    }
                }
            ]
        }

        self.pipeline._print_console_output(results)

        printed_text = '\n'.join(
            str(call.args[0]) for call in mock_print.call_args_list if call.args
        )
        self.assertIn('同業他店と比較した比率の異常値を確認してください', printed_text)

    def test_print_console_output_shows_incomplete_data_warning(self):
        """Places with data_incomplete=True get the 詳細データ未取得 warning and hint printed"""
        import io
        results = {
            'total_places': 1,
            'places': [{
                'name': 'テストイタリアン',
                'category': 'イタリアン',
                'address': 'テスト市テスト町',
                'rating': 4.7,
                'review_count': 0,
                'price_range': '',
                'phone': '',
                'website': '',
                'emails': '',
                'rating_distribution': None,
                'histogram_ascii': None,
                'business_hours': None,
                'sample_reviews': None,
                'data_incomplete': True,
                'data_incomplete_hint': '"テストイタリアン テスト市テスト町" のように店名で直接検索すると取得できます',
            }]
        }

        captured = io.StringIO()
        import sys
        sys.stdout = captured
        try:
            self.pipeline._print_console_output(results)
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn('詳細データ未取得', output,
                      "data_incomplete=True のとき「詳細データ未取得」が出力されること")
        self.assertIn('直接検索', output,
                      "対処方法（直接検索）のヒントが出力されること")


class TestMainFunction(unittest.TestCase):
    """main() tests"""
    
    @patch('sys.argv', ['cli.py', 'テストクエリ'])
    @patch('src.pipeline.GoogleMapsPipeline.extract_places')
    @patch('src.pipeline.GoogleMapsPipeline.analyze_results')
    @patch('src.pipeline.GoogleMapsPipeline._print_console_output')
    def test_main_basic_execution(self, mock_print, mock_analyze, mock_extract):
        """Basic main() execution"""
        mock_extract.return_value = '/tmp/fake.csv'
        mock_analyze.return_value = {
            'total_places': 1,
            'places': [{'name': 'Test'}],
            'summary': {}
        }

        from tools.cli import main
        
        with patch('sys.exit'):
            main()
        
        mock_extract.assert_called_once()
        mock_analyze.assert_called_once()
        mock_print.assert_called_once()
    
    @patch('sys.argv', ['cli.py', 'テストクエリ', '--output', 'test.json'])
    @patch('src.pipeline.GoogleMapsPipeline.extract_places')
    @patch('src.pipeline.GoogleMapsPipeline.analyze_results')
    @patch('src.pipeline.GoogleMapsPipeline._print_console_output')
    @patch('builtins.open', new_callable=mock_open, read_data='{}')
    def test_main_with_json_output(self, mock_open_file, mock_print, mock_analyze, mock_extract):
        """main() execution with JSON output"""
        mock_extract.return_value = '/tmp/fake.csv'
        mock_analyze.return_value = {
            'total_places': 1,
            'places': [{'name': 'Test'}],
            'summary': {}
        }

        from tools.cli import main

        with patch('sys.exit'):
            main()

        mock_extract.assert_called_once()
        mock_analyze.assert_called_once()
        mock_print.assert_called_once()
        # open() is called three times: reading rating_patterns.csv, reading
        # rating_messages.json, and writing test.json. read_data='{}' is the minimal
        # dummy content that keeps both reads from raising ({} is valid as empty
        # JSON, and as CSV it parses safely as a header-only file with 0 records).
        mock_open_file.assert_any_call('test.json', 'w', encoding='utf-8')
        # write() is called multiple times (JSON writing), so only check called
        self.assertTrue(mock_open_file().write.called)

    @patch('sys.argv', ['cli.py', 'テストクエリ'])
    @patch('src.pipeline.GoogleMapsPipeline.analyze_results')
    @patch('src.pipeline.GoogleMapsPipeline._print_console_output')
    def test_main_removes_temp_csv(self, mock_print, mock_analyze):
        """Without --keep-csv, main() deletes the intermediate temp CSV.

        Regression test: tools/cli.py used os.unlink without importing os; the
        resulting NameError was swallowed by the bare except and the temp file
        silently survived."""
        mock_analyze.return_value = {
            'total_places': 1,
            'places': [{'name': 'Test'}],
            'summary': {}
        }

        import tempfile as _tempfile
        fd, temp_csv = _tempfile.mkstemp(suffix='.csv', prefix='gmaps_', dir='/tmp')
        os.close(fd)

        from tools.cli import main

        try:
            with patch('src.pipeline.GoogleMapsPipeline.extract_places',
                       return_value=temp_csv):
                with patch('sys.exit'):
                    main()
            self.assertFalse(os.path.exists(temp_csv),
                             "main()が一時CSVファイルを削除すること")
        finally:
            if os.path.exists(temp_csv):
                os.unlink(temp_csv)

    def test_sample_reviews_full_text_no_truncation(self):
        """Sample reviews are returned in full, without the 100-char limit"""
        pipeline = GoogleMapsPipeline()
        
        # Review data containing a long Description (200+ chars)
        long_review_json = json.dumps([
            {
                "Name": "テストユーザー1",
                "Rating": 5,
                "Description": "これは非常に長いレビューテキストです。" * 10 + "最後まで完全に表示されるべきです。"
            },
            {
                "Name": "テストユーザー2", 
                "Rating": 4,
                "Description": "短いレビュー"
            }
        ])
        
        result = pipeline._parse_sample_reviews(long_review_json)
        
        # Verify the first review is not truncated
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['reviewer_name'], "テストユーザー1")
        self.assertEqual(result[0]['rating'], 5)
        
        # Verify the long Description is fully preserved (does not end with ...)
        description = result[0]['description']
        self.assertGreater(len(description), 100)  # over 100 chars
        self.assertFalse(description.endswith('...'))  # no truncation
        self.assertTrue(description.endswith('最後まで完全に表示されるべきです。'))
        
        # The second review is also intact
        self.assertEqual(result[1]['reviewer_name'], "テストユーザー2")
        self.assertEqual(result[1]['description'], "短いレビュー")

    def test_console_output_shows_both_advice_and_warning_text(self):
        """Both advice_text (base assessment) and warning_text (extra caution) are shown"""
        pipeline = GoogleMapsPipeline()

        test_place = {
            'name': 'テスト店舗',
            'category': 'Restaurant',
            'address': 'テスト住所',
            'rating': 4.2,
            'review_count': 50,
            'price_range': '¥2,000-3,000',
            'phone': '03-1234-5678',
            'website': 'https://test.com',
            'emails': 'test@test.com',
            'rating_advice': {
                'quality_level': 'good',
                'advice_text': '基本的なアドバイスです。',
                'warning_text': '条件付きの追加注意です。',
                'confidence': 'high'
            }
        }

        import io
        import sys
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            test_results = {
                'total_places': 1,
                'places': [test_place],
                'summary': {}
            }
            pipeline._print_console_output(test_results)
            output = captured_output.getvalue()

            # advice_text is shown as the base assessment
            self.assertIn('💡 アドバイス: 基本的なアドバイスです。', output)
            # warning_text is shown as the extra caution
            self.assertIn('⚠️  注意: 条件付きの追加注意です。', output)

        finally:
            sys.stdout = sys.__stdout__

    def test_console_output_shows_only_advice_when_no_warning(self):
        """Only advice_text is shown when warning_text is empty"""
        pipeline = GoogleMapsPipeline()

        test_place = {
            'name': 'テスト店舗',
            'category': 'Restaurant',
            'address': 'テスト住所',
            'rating': 4.5,
            'review_count': 100,
            'price_range': None,
            'phone': None,
            'website': None,
            'emails': None,
            'rating_advice': {
                'quality_level': 'best_of_best',
                'advice_text': '最高クラスの店舗です。',
                'warning_text': '',
                'confidence': 'high'
            }
        }

        import io
        import sys
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            test_results = {
                'total_places': 1,
                'places': [test_place],
                'summary': {}
            }
            pipeline._print_console_output(test_results)
            output = captured_output.getvalue()

            self.assertIn('💡 アドバイス: 最高クラスの店舗です。', output)
            self.assertNotIn('⚠️  注意:', output)

        finally:
            sys.stdout = sys.__stdout__


class TestStdioStreamSafety(unittest.TestCase):
    """On MCP's stdio transport, stdout IS the JSON-RPC channel. Progress or
    diagnostic messages leaking into it break the protocol, so the paths the MCP
    server calls (extract_places / analyze_results) must write nothing to stdout."""

    def setUp(self):
        self.test_scraper_path = '/tmp/fake_scraper_stdio'
        with open(self.test_scraper_path, 'w') as f:
            f.write('#!/bin/bash\necho "mock scraper"')
        os.chmod(self.test_scraper_path, 0o755)
        self.pipeline = GoogleMapsPipeline(scraper_path=self.test_scraper_path)

    def tearDown(self):
        if os.path.exists(self.test_scraper_path):
            os.unlink(self.test_scraper_path)

    @patch('src.pipeline.playwright_driver.ensure_driver', new=lambda: Path('/tmp/fake-driver'))
    @patch('subprocess.run')
    def test_extract_places_writes_nothing_to_stdout(self, mock_subprocess):
        """Extraction progress goes to stderr, stdout stays clean"""
        mock_subprocess.return_value = MagicMock(returncode=0, stderr='')

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            output_file = self.pipeline.extract_places('東京タワー')
        if os.path.exists(output_file):
            os.unlink(output_file)

        self.assertEqual('', stdout.getvalue())
        self.assertIn('Go scraper実行', stderr.getvalue())

    def test_analyze_results_writes_nothing_to_stdout(self):
        """Analysis progress goes to stderr, stdout stays clean"""
        csv_fd, csv_file = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(csv_fd, 'w', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'review_rating', 'review_count'])
            writer.writeheader()
            writer.writerow({'title': '東京タワー', 'review_rating': '4.5', 'review_count': '100'})

        try:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.pipeline.analyze_results(csv_file)

            self.assertEqual('', stdout.getvalue())
            self.assertIn('分析完了', stderr.getvalue())
        finally:
            os.unlink(csv_file)

    def test_rating_distribution_parse_error_warns_to_stderr(self):
        """Even the rating-distribution parse-failure path keeps stdout clean"""
        row = {
            'title': 'テスト店舗',
            'review_rating': '4.0',
            'review_count': '10',
            'reviews_per_rating': '{壊れたJSON',
        }

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.pipeline._parse_place_data(row)

        self.assertEqual('', stdout.getvalue())
        self.assertIn('評価分布解析エラー', stderr.getvalue())


class TestLoadJsonConfig(unittest.TestCase):
    """Tests for load_json_config() (the shared config.json loading logic)

    src/server.py's mixed_ratings_workflow threshold loading also goes through this
    function, so verification here underwrites its configurability.
    """

    def setUp(self):
        from src.pipeline import load_json_config
        self.load_json_config = load_json_config
        self.defaults = {
            "review_selection": {"min_reviews": 10},
            "mixed_ratings_workflow": {"star1_plus_star2_threshold_percent": 15},
        }

    def test_missing_file_returns_defaults(self):
        missing_path = Path('/tmp/does_not_exist_config_12345.json')
        result = self.load_json_config(missing_path, self.defaults)
        self.assertEqual(result, self.defaults)

    def test_explicit_value_overrides_default(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"mixed_ratings_workflow": {"star1_plus_star2_threshold_percent": 20}}, f)
            temp_path = Path(f.name)
        try:
            result = self.load_json_config(temp_path, self.defaults)
            self.assertEqual(result["mixed_ratings_workflow"]["star1_plus_star2_threshold_percent"], 20)
        finally:
            os.remove(temp_path)

    def test_missing_subkey_falls_back_to_default(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"mixed_ratings_workflow": {}}, f)
            temp_path = Path(f.name)
        try:
            result = self.load_json_config(temp_path, self.defaults)
            self.assertEqual(result["mixed_ratings_workflow"]["star1_plus_star2_threshold_percent"], 15)
        finally:
            os.remove(temp_path)

    def test_missing_top_level_key_falls_back_to_default(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"review_selection": {"min_reviews": 50}}, f)
            temp_path = Path(f.name)
        try:
            result = self.load_json_config(temp_path, self.defaults)
            self.assertEqual(result["mixed_ratings_workflow"], self.defaults["mixed_ratings_workflow"])
        finally:
            os.remove(temp_path)

    def test_malformed_json_falls_back_to_defaults(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{壊れたJSON')
            temp_path = Path(f.name)
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = self.load_json_config(temp_path, self.defaults)
            self.assertEqual(result, self.defaults)
            self.assertIn('設定ファイル読み込みエラー', stderr.getvalue())
        finally:
            os.remove(temp_path)


if __name__ == '__main__':
    unittest.main(verbosity=2)