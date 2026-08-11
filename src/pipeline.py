#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps Pipeline Core Logic
"""

import subprocess
import tempfile
import os
import sys
import json
import csv
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
import time
from datetime import datetime, timedelta

from .rating_analyzer import RuleBasedRatingAnalyzer, DEFAULT_STAR5_DOMINANCE_CONFIG
from . import playwright_driver


def _diag(message: str) -> None:
    """Emit progress/diagnostic messages to stderr.

    On MCP's stdio transport, stdout IS the JSON-RPC channel; mixing human-oriented
    messages into it breaks the protocol. CLI result output
    (_print_console_output / run_pipeline) may stay on stdout.
    """
    print(message, file=sys.stderr)


def _stream_output(pipe, label: str, buffer: List[str]) -> None:
    """Drain a subprocess pipe line by line, logging each line as it arrives.

    Meant to run in its own thread (one per stdout/stderr) so both streams
    are drained concurrently - reading only one risks deadlock once the
    other's OS pipe buffer fills - and so a hang shows up in the logs as it
    happens, one line at a time with its own log timestamp, instead of
    staying silent until the process exits (or times out).
    """
    for line in pipe:
        buffer.append(line)
        _diag(f"{label} {line.rstrip()}")


def load_json_config(config_path: Path, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Load the config file (config.json), merging defaults key by key.

    Missing top-level keys are filled from the defaults; when a value is a dict,
    its immediate subkeys are filled the same way. This is the single loading
    logic shared regardless of caller section (src/server.py's
    mixed_ratings_workflow settings also go through here).
    """
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for key, value in defaults.items():
                    if key not in config:
                        config[key] = value
                    elif isinstance(value, dict):
                        for subkey, subvalue in value.items():
                            if subkey not in config[key]:
                                config[key][subkey] = subvalue
                return config
        else:
            return defaults
    except Exception as e:
        _diag(f"⚠️  設定ファイル読み込みエラー: {e}")
        return defaults


class GoogleMapsPipeline:
    """End-to-end pipeline from Google Maps search to analysis"""
    
    def __init__(self, scraper_path: str = None):
        self.scraper_path = scraper_path or str(Path(__file__).parent.parent / 'google-maps-scraper' / 'bin' / 'google_maps_scraper')
        self.config_path = Path(__file__).parent.parent / 'config.json'
        if not os.path.exists(self.scraper_path):
            raise FileNotFoundError(f"Go scraper binary not found: {self.scraper_path}")
        
        # Initialize rating analyzer
        pattern_file = str(Path(__file__).parent.parent / 'data' / 'rating_patterns.csv')
        star5_dominance_config = load_json_config(
            self.config_path, {"star5_dominance_check": DEFAULT_STAR5_DOMINANCE_CONFIG}
        )["star5_dominance_check"]
        self.rating_analyzer = RuleBasedRatingAnalyzer(
            pattern_file, star5_dominance_config=star5_dominance_config
        )
    
    def extract_places(self, query: str,
                      max_results: int = 20,
                      output_file: str = None,
                      extra_reviews: bool = False,  # Disabled: Google RPC API changed ~Dec 2025; causes 60s+ hang
                      concurrency: int = 8) -> str:
        """
        Extract data from Google Maps using the Go scraper

        Args:
            query: free-form search query (e.g. "寿司 渋谷", "東京駅近くの美味しいラーメン屋")
            max_results: maximum number of results
            output_file: output CSV file path (a temp file when None)
            extra_reviews: flag to fetch extended reviews
            concurrency: number of parallel workers

        Returns:
            str: path of the output CSV file
        """
        if output_file is None:
            temp_fd, output_file = tempfile.mkstemp(suffix='.csv', prefix='gmaps_')
            os.close(temp_fd)

        # Write the search query file
        query_fd, query_file = tempfile.mkstemp(suffix='.txt', prefix='query_')
        try:
            with os.fdopen(query_fd, 'w', encoding='utf-8') as f:
                f.write(f"{query}\n")
            
            # Build the Go scraper command.
            # concurrency=1 is mandatory: with parallelism > 1 Google serves lite
            # pages and reviews_per_rating (the rating distribution) goes missing.
            # NOTE: -extra-reviews is disabled because Google's RPC API change
            # (~Dec 2025) makes it hang for 60s+. To re-enable, restore:
            #   effective_concurrency = 1 if extra_reviews else concurrency
            #   if extra_reviews: cmd.append('-extra-reviews')
            effective_concurrency = 1
            cmd = [
                self.scraper_path,
                '-input', query_file,
                '-results', output_file,
                '-c', str(effective_concurrency),
                '-depth', str(max_results // 10 + 1),
                '-lang', 'ja',
            ]
            
            _diag(f"🚀 Go scraper実行: {query}")
            _diag(f"📝 コマンド: {' '.join(cmd)}")

            # playwright-go's driver-download CDN is decommissioned, so guarantee a
            # valid driver and point PLAYWRIGHT_DRIVER_PATH at it (already-assembled
            # drivers just pass validation). See src/playwright_driver.py's module
            # docstring for details.
            driver_dir = playwright_driver.ensure_driver()
            scraper_env = dict(os.environ, PLAYWRIGHT_DRIVER_PATH=str(driver_dir))

            # Popen + threaded line-by-line draining, not subprocess.run(capture_output=True):
            # a run that hangs partway through must leave a partial trail in the logs (which
            # lines arrived, and when) instead of total silence until the process exits or
            # times out. A production incident where 0-result runs left zero diagnosable
            # trace for their full duration is what made this gap visible.
            start_time = time.time()
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, env=scraper_env)
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []
            stdout_thread = threading.Thread(
                target=_stream_output, args=(process.stdout, "📤 stdout:", stdout_lines)
            )
            stderr_thread = threading.Thread(
                target=_stream_output, args=(process.stderr, "⚠️  stderr:", stderr_lines)
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                returncode = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError("Go scraper timed out after 600s")
            finally:
                stdout_thread.join()
                stderr_thread.join()

            execution_time = time.time() - start_time

            if returncode != 0:
                raise RuntimeError(f"Go scraper failed: {''.join(stderr_lines)}")

            _diag(f"✅ データ抽出完了 ({execution_time:.2f}秒)")
            # Store execution time as attribute for later use
            self._last_extraction_time = execution_time
            # scrapemate (unmodified upstream) always logs this exact message via
            # s.log.Error when a job fails mid-processing - e.g. a bot-check page
            # has no div[role='feed'], so scroll() throws reading its scrollHeight.
            # The process can still exit 0, so this is the only signal available
            # without modifying the vendored Go source.
            self._last_extraction_had_job_error = any(
                'error while processing job' in line
                for line in stdout_lines + stderr_lines
            )
            return output_file
            
        finally:
            if os.path.exists(query_file):
                os.unlink(query_file)
    
    def analyze_results(self, csv_file: str, detailed_info: bool = True) -> Dict[str, Any]:
        """
        Analyze extraction results and return structured data

        Args:
            csv_file: CSV file to analyze

        Returns:
            Dict: structured analysis result
        """
        _diag(f"📊 結果分析開始: {csv_file}")
        analysis_start_time = time.time()

        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"CSV file not found: {csv_file}")

        results = []
        total_places = 0

        try:
            # Raise the CSV field size limit
            csv.field_size_limit(sys.maxsize)
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    total_places += 1
                    place_data = self._parse_place_data(row, detailed_info=detailed_info)
                    results.append(place_data)
            
            analysis_time = time.time() - analysis_start_time
            _diag(f"✅ 分析完了: {total_places}件の店舗データを処理 ({analysis_time:.2f}秒)")

            return {
                'total_places': total_places,
                'places': results,
                'summary': self._generate_summary(results),
                'area_search_notice': (
                    self.rating_analyzer.messages.get('area_search_notice')
                    if total_places > 1 else None
                ),
                'scrape_processing_error_notice': (
                    self.rating_analyzer.messages.get('scrape_processing_error_notice')
                    if getattr(self, '_last_extraction_had_job_error', False) else None
                ),
                'timing': {
                    'analysis_time': analysis_time
                }
            }
            
        except Exception as e:
            _diag(f"❌ 分析エラー: {e}")
            raise
    
    def _parse_place_data(self, row: Dict[str, str], detailed_info: bool = False) -> Dict[str, Any]:
        """Convert one CSV row into structured data"""
        # Safe numeric conversion
        try:
            rating = float(row.get('review_rating', 0)) if row.get('review_rating') else None
        except (ValueError, TypeError):
            rating = None
            
        try:
            review_count = int(row.get('review_count', 0)) if row.get('review_count') else 0
        except (ValueError, TypeError):
            review_count = 0
        
        place = {
            'name': row.get('title', ''),
            'category': row.get('category', ''),
            'address': row.get('address', ''),
            'rating': rating,
            'review_count': review_count,
            'price_range': row.get('price_range', ''),
            'phone': row.get('phone', ''),
            'website': row.get('website', ''),
            'emails': row.get('emails', ''),
            'rating_distribution': None,
            'histogram_ascii': None,
            'business_hours': None,
            'sample_reviews': None
        }
        
        # Per-star rating distribution
        if row.get('reviews_per_rating'):
            try:
                rating_dist = json.loads(row['reviews_per_rating'])
                total = sum(int(count) for count in rating_dist.values() if count)
                
                if total > 0:
                    distribution = {}
                    histogram_lines = []
                    
                    for star in ['5', '4', '3', '2', '1']:
                        count = int(rating_dist.get(star, 0))
                        percentage = (count / total * 100) if total > 0 else 0
                        bar = '█' * int(percentage / 5)  # one char per 5% (kept from the original logic)
                        
                        distribution[f'star_{star}'] = {
                            'count': count,
                            'percentage': round(percentage, 1)
                        }
                        histogram_lines.append(f'★{star}: {count:3d}件 ({percentage:4.1f}%) {bar}')
                    
                    place['rating_distribution'] = distribution
                    place['histogram_ascii'] = '\n'.join(histogram_lines)
                    
                    # Add rating advice analysis
                    # Convert distribution keys to integers for analyzer
                    rating_counts = {}
                    for key, data in distribution.items():
                        if key.startswith('star_'):
                            star_num = int(key.replace('star_', ''))
                            rating_counts[star_num] = data['count']
                    
                    advice_result = self.rating_analyzer.analyze_distribution(rating_counts)
                    place['rating_advice'] = advice_result
                    
            except Exception as e:
                _diag(f"⚠️  評価分布解析エラー ({place['name']}): {e}")
        
        # Incomplete-data flag: on category searches the Go scraper sometimes
        # skips the detail page for some places
        if review_count == 0 and place['rating_distribution'] is None:
            place['data_incomplete'] = True
            name = place['name']
            place['data_incomplete_hint'] = (
                f'"{name}" のように店名で直接検索すると取得できます'
            )
        else:
            place['data_incomplete'] = False

        # Detailed info
        if detailed_info:
            # Business hours
            if row.get('open_hours'):
                place['business_hours'] = self._parse_business_hours(row['open_hours'])

            # Extended reviews
            if row.get('user_reviews_extended'):
                place['sample_reviews'] = self._parse_sample_reviews(row['user_reviews_extended'])
        
        return place
    
    def _generate_summary(self, places: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate an overall summary"""
        if not places:
            return {}

        # Rating statistics
        ratings = [p['rating'] for p in places if p['rating'] is not None]
        review_counts = [p['review_count'] for p in places if p['review_count'] > 0]
        
        summary = {
            'average_rating': round(sum(ratings) / len(ratings), 2) if ratings else None,
            'total_reviews': sum(review_counts),
            'places_with_rating': len(ratings),
            'top_rated_places': sorted(
                [p for p in places if p['rating'] is not None], 
                key=lambda x: x['rating'], 
                reverse=True
            )[:5]
        }
        
        return summary
    
    def _parse_business_hours(self, hours_json: str) -> Dict[str, Any]:
        """Convert business-hours JSON into structured data"""
        try:
            hours_data = json.loads(hours_json)
            formatted_hours = []
            
            for day, times in hours_data.items():
                if isinstance(times, list) and times:
                    times_str = ', '.join(times)
                    formatted_hours.append(f"{day}: {times_str}")
                else:
                    formatted_hours.append(f"{day}: {times}")
            
            return {
                'raw': hours_data,
                'formatted': '\n'.join(formatted_hours)
            }
        except Exception as e:
            # JSON parse failure
            hours_text = hours_json
            if len(hours_text) > 100:
                hours_text = hours_text[:100] + '...'
            return {
                'raw': None,
                'formatted': hours_text,
                'parse_error': str(e)
            }
    
    def _parse_sample_reviews(self, reviews_json: str) -> List[Dict[str, str]]:
        """Extract sample reviews from extended-review JSON using adaptive selection"""
        try:
            reviews = json.loads(reviews_json)
            if not reviews or not isinstance(reviews, list):
                return []

            config = self.load_config()
            review_config = config.get('review_selection', {})

            return self.adaptive_review_selection(reviews, review_config)

        except Exception as e:
            return [{'parse_error': str(e)}]

    def load_config(self) -> Dict[str, Any]:
        """Load the config file, falling back to defaults"""
        default_config = {
            "review_selection": {
                "recent_years": 1,
                "selection_mode": "best_worst_pair",
                "fallback_strategy": "expand_period",
                "max_years": 3,
                "min_reviews": 10
            }
        }
        return load_json_config(self.config_path, default_config)
    

    def filter_reviews_by_period(self, reviews: List[Dict[str, Any]], years: int) -> List[Dict[str, Any]]:
        """Filter reviews to those within the given period"""
        if not reviews:
            return []
            
        cutoff_date = datetime.now() - timedelta(days=years * 365)
        filtered_reviews = []
        
        for review in reviews:
            try:
                # Parse the review date (YYYY-MM-DD expected)
                review_date_str = review.get('When', '')
                if review_date_str:
                    # Handle multiple date formats
                    review_date = None
                    for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d-%H-%M-%S']:
                        try:
                            review_date = datetime.strptime(review_date_str.split('T')[0], fmt.split(' ')[0])
                            break
                        except ValueError:
                            continue
                    
                    if review_date and review_date >= cutoff_date:
                        # Only include reviews that have comment text
                        if review.get('Description', '').strip():
                            filtered_reviews.append(review)
            except Exception:
                # Ignore date-parse errors and move on
                continue
                
        return filtered_reviews
    
    def find_rating_extremes(self, reviews: List[Dict[str, Any]]) -> tuple[int, int]:
        """Get the maximum and minimum ratings from a review list"""
        if not reviews:
            return None, None
            
        ratings = [review.get('Rating', 0) for review in reviews if review.get('Rating') is not None]
        if not ratings:
            return None, None
            
        return max(ratings), min(ratings)
    
    def select_latest_by_rating(self, reviews: List[Dict[str, Any]], max_rating: int, min_rating: int) -> List[Dict[str, str]]:
        """Select the latest review for the highest and lowest ratings"""
        if not reviews or max_rating is None or min_rating is None:
            return []

        # Sort highest-rated reviews by date (newest first)
        max_reviews = [r for r in reviews if r.get('Rating') == max_rating]
        max_reviews.sort(key=lambda x: x.get('When', ''), reverse=True)

        # Sort lowest-rated reviews by date (newest first)
        min_reviews = [r for r in reviews if r.get('Rating') == min_rating]
        min_reviews.sort(key=lambda x: x.get('When', ''), reverse=True)

        selected_reviews = []

        # Latest of the highest rating
        if max_reviews:
            review = max_reviews[0]
            selected_reviews.append({
                'reviewer_name': review.get('Name', '名前なし'),
                'rating': review.get('Rating', 'なし'),
                'description': review.get('Description', '')
            })
        
        # Latest of the lowest rating (only when it differs from the highest)
        if min_reviews and max_rating != min_rating:
            review = min_reviews[0]
            selected_reviews.append({
                'reviewer_name': review.get('Name', '名前なし'),
                'rating': review.get('Rating', 'なし'),
                'description': review.get('Description', '')
            })
            
        return selected_reviews
    
    def adaptive_review_selection(self, reviews: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Adaptive review selection via stepwise period expansion"""
        if not reviews:
            return []

        selection_mode = config.get('selection_mode', 'best_worst_pair')

        # Anything other than best_worst_pair uses the legacy method (fast fallback)
        if selection_mode != 'best_worst_pair':
            fallback_reviews = []
            for review in reviews[:2]:  # first two only
                fallback_reviews.append({
                    'reviewer_name': review.get('Name', '名前なし'),
                    'rating': review.get('Rating', 'なし'),
                    'description': review.get('Description', '')
                })
            return fallback_reviews
            
        recent_years = config.get('recent_years', 1)
        max_years = config.get('max_years', 3)
        min_reviews = config.get('min_reviews', 10)
        fallback_strategy = config.get('fallback_strategy', 'expand_period')
        
        # Stepwise period expansion
        for years in range(recent_years, max_years + 1):
            filtered_reviews = self.filter_reviews_by_period(reviews, years)

            if len(filtered_reviews) >= min_reviews:
                # Enough reviews: run the selection
                max_rating, min_rating = self.find_rating_extremes(filtered_reviews)
                if max_rating is not None and min_rating is not None:
                    selected = self.select_latest_by_rating(filtered_reviews, max_rating, min_rating)
                    if selected:
                        return selected
        
        # Still short at the maximum period: select from all time
        if fallback_strategy == 'expand_period':
            max_rating, min_rating = self.find_rating_extremes(reviews)
            if max_rating is not None and min_rating is not None:
                return self.select_latest_by_rating(reviews, max_rating, min_rating)

        # Final fallback: legacy method
        return reviews[:2] if len(reviews) >= 2 else reviews

    def _print_console_output(self, results: Dict[str, Any]) -> None:
        """Print results to the console (equivalent to the old analyzer's output)"""
        print(f'Google Maps分析結果: {results["total_places"]}件')
        print('=' * 60)
        
        for i, place in enumerate(results['places'], 1):
            print(f'\n{i}. {place["name"]}')
            print(f'   カテゴリ: {place["category"]}')
            print(f'   住所: {place["address"]}')
            print(f'   評価: {place["rating"]:.6f} ({place["review_count"]}件)')
            print(f'   価格帯: {place["price_range"]}')
            print(f'   電話: {place["phone"]}')
            print(f'   ウェブサイト: {place["website"]}')
            print(f'   メール: {place["emails"]}')
            
            # Business hours
            if place.get('business_hours'):
                print('   営業時間:')
                print(f'     {place["business_hours"]["formatted"]}')

            # Incomplete data
            if place.get('data_incomplete'):
                print(f'   ⚠️  詳細データ未取得（レビュー件数・分布が取得できませんでした）')
                print(f'   💡 直接検索で取得できます: {place["data_incomplete_hint"]}')

            # Rating distribution histogram
            if place.get('histogram_ascii'):
                print('   星別評価分布:')
                for line in place['histogram_ascii'].split('\n'):
                    print(f'     {line}')
            
            # Rating advice analysis
            if place.get('rating_advice'):
                advice = place['rating_advice']
                print(f'   📊 評価分布分析: {advice["quality_level"].upper()}')
                if advice.get('advice_text'):
                    print(f'   💡 アドバイス: {advice["advice_text"]}')
                if advice.get('warning_text'):
                    print(f'   ⚠️  注意: {advice["warning_text"]}')
                print(f'   🎯 信頼度: {advice["confidence"]}')
                if advice.get('general_disclaimer'):
                    print(f'   📌 {advice["general_disclaimer"]}')
                if advice.get('star5_dominance_notice'):
                    print(f'   🚩 {advice["star5_dominance_notice"]}')
                if advice.get('template_notice'):
                    print(f'   ℹ️  {advice["template_notice"]}')
            
            # Sample reviews
            if place.get('sample_reviews') and place['sample_reviews']:
                print(f'   詳細レビュー数: {place["review_count"]}件')
                print('   最新レビュー例:')
                for j, review in enumerate(place['sample_reviews']):
                    if 'parse_error' not in review:
                        print(f'     {j+1}. {review["reviewer_name"]} - 評価: {review["rating"]}')
                        if review.get('description'):
                            print(f'        {review["description"]}')
                            
                if i >= 3:  # show details for the first 3 places only
                    break
    
    def run_pipeline(self, query: str, detailed_info: bool = True, **kwargs) -> Dict[str, Any]:
        """
        Run the end-to-end pipeline

        Args:
            query: free-form search query
            detailed_info: whether to include details (business hours, sample reviews)
            **kwargs: other arguments passed through to extract_places

        Returns:
            Dict: analysis result
        """
        print(f"🎯 Google Maps Pipeline開始: '{query}'")
        total_start_time = time.time()

        # Step 1: extract data
        csv_file = self.extract_places(query, **kwargs)
        extraction_time = getattr(self, '_last_extraction_time', 0)

        try:
            # Step 2: analyze
            results = self.analyze_results(csv_file, detailed_info=detailed_info)
            analysis_time = results.get('timing', {}).get('analysis_time', 0)

            total_time = time.time() - total_start_time

            # Print the timing breakdown
            print("\n" + "="*60)
            print("⏱️  処理時間内訳")
            print("="*60)
            print(f"Go scraper実行: {extraction_time:.2f}秒 ({extraction_time/total_time*100:.1f}%)")
            print(f"Python解析処理: {analysis_time:.2f}秒 ({analysis_time/total_time*100:.1f}%)")
            print(f"その他オーバーヘッド: {total_time-extraction_time-analysis_time:.2f}秒 ({(total_time-extraction_time-analysis_time)/total_time*100:.1f}%)")
            print(f"合計時間: {total_time:.2f}秒")
            
            # Attach timing info to the result
            results.setdefault('timing', {}).update({
                'extraction_time': extraction_time,
                'total_time': total_time
            })

            # Step 3: console output
            print("\n" + "="*60)
            print("📋 詳細分析結果")
            print("="*60)
            self._print_console_output(results)
            
            return results
            
        finally:
            # Remove the temp file
            if csv_file.startswith('/tmp/'):
                try:
                    os.unlink(csv_file)
                except:
                    pass
