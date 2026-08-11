#!/usr/bin/env python3
"""
Rule-based rating distribution analyzer for Google Maps reviews
Provides deterministic advice based on rating pattern matching
"""
import csv
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from collections import Counter, OrderedDict

DEFAULT_MESSAGES_FILE = Path(__file__).resolve().parent.parent / 'data' / 'rating_messages.json'

# Thresholds for detecting distributions where ★5 is disproportionately high
# relative to peer stores. Empirically calibrated against real store
# distributions (overridable via config.json's star5_dominance_check).
DEFAULT_STAR5_DOMINANCE_CONFIG = {
    "high_ratio_percent": 80,
    "moderate_ratio_percent": 65,
    "moderate_count_threshold": 500,
}


class QualityLevel:
    """
    Allowed values of the quality_level column. Values in data/rating_patterns.csv
    must match these. Comparisons and assertions must go through these constants so
    the string literals never get hardcoded again elsewhere.
    """
    BEST_OF_BEST = "best_of_best"
    BEST = "best"
    CASE_BY_CASE = "case_by_case"
    LOW_RATING_DOMINANT = "low_rating_dominant"
    REVIEW_CHECK_RECOMMENDED = "review_check_recommended"
    MISC = "misc"
    UNKNOWN = "unknown"

    @classmethod
    def all_values(cls) -> set:
        return {
            cls.BEST_OF_BEST, cls.BEST, cls.CASE_BY_CASE,
            cls.LOW_RATING_DOMINANT, cls.REVIEW_CHECK_RECOMMENDED,
            cls.MISC, cls.UNKNOWN,
        }


class RuleBasedRatingAnalyzer:
    """
    Analyzes Google Maps rating distributions using rule-based pattern matching

    Supports both fixed patterns (e.g., '54321') and wildcard patterns (e.g., 'xx312')
    with priority-based matching to ensure deterministic results.
    """

    def __init__(self, pattern_file: str, messages_file: Optional[str] = None,
                 star5_dominance_config: Optional[Dict[str, Any]] = None):
        """
        Initialize analyzer with pattern definitions from CSV file

        Args:
            pattern_file: Path to CSV file containing rating patterns and advice
            messages_file: Path to JSON file containing common notice text
                (template_notice/general_disclaimer/empty & unknown fallback text).
                Defaults to data/rating_messages.json.
            star5_dominance_config: Overrides for DEFAULT_STAR5_DOMINANCE_CONFIG
                (high_ratio_percent/moderate_ratio_percent/moderate_count_threshold).
        """
        self.patterns = self._load_patterns(pattern_file)
        self.messages = self._load_messages(messages_file or DEFAULT_MESSAGES_FILE)
        self.star5_dominance_config = {
            **DEFAULT_STAR5_DOMINANCE_CONFIG,
            **(star5_dominance_config or {}),
        }
    
    def analyze_distribution(self, rating_dist: Dict[int, int]) -> Dict[str, Any]:
        """
        Analyze rating distribution and provide advice with wildcard matching
        
        Args:
            rating_dist: Dictionary mapping rating (1-5) to count
            
        Returns:
            Dictionary containing pattern, quality level, advice, and warnings
        """
        if not rating_dist:
            result = {
                'pattern': 'empty',
                'quality_level': QualityLevel.UNKNOWN,
                'advice_text': self.messages['empty_advice_text'],
                'warning_text': '',
                'confidence': 'low'
            }
        else:
            actual_pattern = self._get_pattern_key(rating_dist)

            # Try to find best matching pattern (fixed patterns first, then wildcards)
            matched_pattern, pattern_data = self._find_best_wildcard_match(actual_pattern, self.patterns)

            if matched_pattern and pattern_data:
                result = {
                    'pattern': matched_pattern,
                    'quality_level': pattern_data['quality_level'],
                    'advice_text': pattern_data['advice_text'],
                    'warning_text': pattern_data['warning_text'],
                    'confidence': pattern_data['confidence']
                }
            else:
                result = {
                    'pattern': actual_pattern,
                    'quality_level': QualityLevel.UNKNOWN,
                    'advice_text': self.messages['unknown_advice_text'].format(pattern=actual_pattern),
                    'warning_text': self.messages['unknown_warning_text'],
                    'confidence': 'low'
                }

        # Common notices attached regardless of quality_level
        result['template_notice'] = self.messages['template_notice']
        result['general_disclaimer'] = self.messages['general_disclaimer']
        result['star5_dominance_notice'] = self._check_star5_dominance(rating_dist)
        return result

    def _check_star5_dominance(self, rating_dist: Dict[int, int]) -> Optional[str]:
        """
        Flag distributions where star5 is disproportionately high in absolute terms
        (fixed thresholds; never compared against any other store's data) -
        independent of quality_level/pattern matching, since a legitimate-looking
        monotonic pattern (e.g. 54321/best_of_best) can still cross these
        thresholds.

        Returns the notice text if either threshold is met, else None:
        - star5 ratio > high_ratio_percent, or
        - star5 ratio >= moderate_ratio_percent and star5 count > moderate_count_threshold
        """
        total = sum(rating_dist.values())
        if total == 0:
            return None

        star5_count = rating_dist.get(5, 0)
        star5_ratio = star5_count / total * 100
        cfg = self.star5_dominance_config

        if star5_ratio > cfg['high_ratio_percent']:
            return self.messages['star5_dominance_notice']
        if star5_ratio >= cfg['moderate_ratio_percent'] and star5_count > cfg['moderate_count_threshold']:
            return self.messages['star5_dominance_notice']
        return None
    
    def _get_pattern_key(self, rating_dist: Dict[int, int]) -> str:
        """
        Convert rating distribution to pattern key (e.g., '54321')
        
        Args:
            rating_dist: Dictionary mapping rating to count
            
        Returns:
            Pattern string with ratings sorted by frequency (high to low)
        """
        # Sort ratings by count (descending), then by rating value (descending) for ties
        sorted_ratings = sorted(
            rating_dist.items(), 
            key=lambda x: (x[1], x[0]), 
            reverse=True
        )
        
        # Create pattern string from sorted ratings
        pattern = ''.join(str(rating) for rating, count in sorted_ratings)
        return pattern
    
    def _load_patterns(self, pattern_file: str) -> OrderedDict[str, Dict[str, str]]:
        """
        Load pattern definitions from CSV file, preserving row order for priority
        
        Args:
            pattern_file: Path to CSV file
            
        Returns:
            OrderedDict mapping pattern keys to pattern data in CSV row order
        """
        patterns = OrderedDict()
        
        with open(pattern_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                pattern_key = row['pattern']
                patterns[pattern_key] = {
                    'quality_level': row['quality_level'],
                    'advice_text': row['advice_text'],
                    'warning_text': row['warning_text'],
                    'confidence': row['confidence']
                }
        
        return patterns

    def _load_messages(self, messages_file: str) -> Dict[str, str]:
        """
        Load common notice text (template_notice/general_disclaimer/fallback text) from JSON file

        Args:
            messages_file: Path to JSON file

        Returns:
            Dict mapping message keys to text
        """
        with open(messages_file, 'r', encoding='utf-8') as file:
            return json.load(file)

    def _matches_wildcard_pattern(self, actual_pattern: str, wildcard_pattern: str) -> bool:
        """
        Check if actual pattern matches wildcard pattern
        
        Args:
            actual_pattern: Actual rating pattern (e.g., '54312')
            wildcard_pattern: Wildcard pattern (e.g., 'xx312')
            
        Returns:
            True if patterns match, False otherwise
        """
        if len(actual_pattern) != len(wildcard_pattern):
            return False
        
        for actual_char, wildcard_char in zip(actual_pattern, wildcard_pattern):
            if wildcard_char != 'x' and actual_char != wildcard_char:
                return False
        
        return True
    
    def _find_best_wildcard_match(self, actual_pattern: str, patterns: OrderedDict[str, Dict[str, str]]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
        """
        Find best matching pattern using CSV row order as priority
        
        Args:
            actual_pattern: Actual rating pattern
            patterns: OrderedDict of patterns in CSV row order
            
        Returns:
            Tuple of (matched_pattern, pattern_data) or (None, None)
        """
        # Iterate through patterns in CSV row order (top to bottom)
        for pattern_key, pattern_data in patterns.items():
            if self._matches_wildcard_pattern(actual_pattern, pattern_key):
                return pattern_key, pattern_data
        
        return None, None