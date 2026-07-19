#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests: end-to-end tests using the real Go scraper binary

Run only in environments where the binary exists.
Requires network access and a Playwright browser.

Run: python -m pytest test/test_integration.py -v
"""

import unittest
import os
import sys
import csv
import subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.pipeline import GoogleMapsPipeline

_BINARY_PATH = str(
    Path(__file__).parent.parent / 'google-maps-scraper' / 'bin' / 'google_maps_scraper'
)
_binary_exists = os.path.exists(_BINARY_PATH)


@unittest.skipUnless(_binary_exists, f"Go scraper binary not found: {_BINARY_PATH}")
class TestIntegration(unittest.TestCase):
    """End-to-end integration tests using the real Go binary"""

    def setUp(self):
        self.pipeline = GoogleMapsPipeline(scraper_path=_BINARY_PATH)

    def test_extra_reviews_flag_not_in_actual_subprocess_command(self):
        """
        Record the command actually passed to the binary with a spy and verify
        it does not contain -extra-reviews. Unlike a mock, this goes through
        the real subprocess.run.
        """
        captured_cmds = []
        original_run = subprocess.run

        def spy_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return original_run(cmd, **kwargs)

        with patch('subprocess.run', side_effect=spy_run):
            csv_path = self.pipeline.extract_places(
                '東京タワー', max_results=5, concurrency=2
            )

        try:
            # ensure_driver()'s driver validation (node cli.js --version) goes through
            # the same spy, so pick out only the calls to the scraper binary
            scraper_cmds = [c for c in captured_cmds if c and c[0] == _BINARY_PATH]
            self.assertGreater(len(scraper_cmds), 0, "scraperバイナリが1回以上呼ばれること")
            actual_cmd = scraper_cmds[0]

            self.assertNotIn(
                '-extra-reviews', actual_cmd,
                f"実際のコマンドに -extra-reviews が含まれてはならない。\n実コマンド: {actual_cmd}"
            )

            # Verify -c is always 1 for rating-distribution retrieval
            # (with parallelism > 1 Google serves lite pages and reviews_per_rating goes missing)
            c_idx = actual_cmd.index('-c')
            self.assertEqual(
                actual_cmd[c_idx + 1], '1',
                f"評価分布取得のため -c は 1 でなければならない。\n実コマンド: {actual_cmd}"
            )

        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_pipeline_produces_valid_csv_output(self):
        """Run the real binary and verify a CSV is produced and contains data"""
        csv_path = self.pipeline.extract_places(
            '東京タワー', max_results=5, concurrency=2
        )
        try:
            self.assertTrue(os.path.exists(csv_path), "CSVファイルが生成されること")
            self.assertGreater(os.path.getsize(csv_path), 0, "CSVファイルが空でないこと")

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertGreater(len(rows), 0, "CSVに1件以上のデータが含まれること")
            self.assertIn('title', rows[0], "CSVに title 列が含まれること")

        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_rating_distribution_present_in_real_output(self):
        """Verify the rating distribution is actually retrievable thanks to concurrency=1"""
        csv_path = self.pipeline.extract_places(
            '東京タワー', max_results=5, concurrency=2
        )
        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)

            places_with_distribution = [
                p for p in result['places'] if p.get('rating_distribution') is not None
            ]
            self.assertGreater(
                len(places_with_distribution), 0,
                "少なくとも1件は rating_distribution が取得できること "
                "（concurrency=1 でないと Google が lite ページを返す）"
            )

            place = places_with_distribution[0]
            dist = place['rating_distribution']
            self.assertIn('star_5', dist)
            self.assertIn('star_1', dist)
            self.assertGreater(
                place['review_count'], 0,
                "review_count が 0 でないこと"
            )
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_analyze_results_on_real_csv(self):
        """Verify analyze_results can process an actually scraped CSV"""
        csv_path = self.pipeline.extract_places(
            '東京タワー', max_results=5, concurrency=2
        )
        try:
            result = self.pipeline.analyze_results(csv_path, detailed_info=False)

            self.assertIn('total_places', result)
            self.assertGreater(result['total_places'], 0)
            self.assertIn('places', result)
            self.assertIn('summary', result)

            first_place = result['places'][0]
            self.assertIn('name', first_place)
            self.assertIsNotNone(first_place['name'])

        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

if __name__ == '__main__':
    unittest.main(verbosity=2)
