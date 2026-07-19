#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests that the place_ratings_analyze tool description (the text handed to MCP
clients / AI agents) properly states the limits of rating-distribution analysis.

Background: looking only at a quality_level label (best_of_best etc.) risked the
misreading "natural-looking distribution = trustworthy = no fake-review concern",
so the limits are stated at the tool-description level.

The description itself is not hardcoded in Python source; it is loaded from
data/mcp_tool_descriptions/place_ratings_analyze.md (same external-file policy
as rating_analyzer.py's template_notice/general_disclaimer).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import server

DESCRIPTION_FILE = (
    Path(__file__).parent.parent / 'data' / 'mcp_tool_descriptions' / 'place_ratings_analyze.md'
)


class TestSearchGoogleMapsDescription:
    """Verify the content of the place_ratings_analyze tool description"""

    def setup_method(self):
        self.doc = server._PLACE_RATINGS_ANALYZE_DESCRIPTION

    def test_description_exists(self):
        assert self.doc is not None
        assert len(self.doc) > 0

    def test_description_is_loaded_verbatim_from_external_file(self):
        """The description's source of truth is data/mcp_tool_descriptions/place_ratings_analyze.md,
        not re-hardcoded as separate text inside the Python source"""
        assert self.doc == DESCRIPTION_FILE.read_text(encoding='utf-8')

    def test_missing_description_file_raises_clear_error(self):
        """A missing description file fails startup with a clear error"""
        import pytest
        with pytest.raises(FileNotFoundError):
            server._load_tool_description('does_not_exist.md')

    def test_mentions_advice_text_is_template(self):
        """States that advice_text/warning_text are templates, not dynamically computed from measurements"""
        assert 'テンプレート' in self.doc

    def test_states_quality_level_label_alone_is_not_a_verdict(self):
        """States not to judge a place by the quality_level label alone (as a caution common to all results, without naming specific labels)"""
        assert 'ラベルだけ' in self.doc

    def test_instructs_presenting_distribution_alongside_label(self):
        """Instructs presenting rating_distribution alongside the results"""
        assert 'rating_distribution' in self.doc

    def test_mentions_sample_reviews_unavailable(self):
        """The existing limitation (sample_reviews unavailable) is still explained"""
        assert 'sample_reviews' in self.doc

    def test_mentions_confirm_on_google_maps_directly(self):
        """Encourages verifying directly on Google Maps as the final check"""
        assert 'Googleマップ' in self.doc or 'Google マップ' in self.doc

    def test_states_quality_level_assumption_and_limits(self):
        """States explicitly that the quality_level classification is only a rough guide
        built on the premise "good places decline in the order ★5→★4→★3→★2→★1",
        and a high-looking label is no proof that it reflects reality."""
        assert '前提' in self.doc
        assert '証明にはならず' in self.doc

    def test_instructs_not_to_leak_raw_field_names_to_user(self):
        """Explicitly forbids the LLM from exposing field/column names like
        quality_level/advice_text verbatim to the user (a CSV column name actually
        leaked into user-facing text once; this codifies the prevention)"""
        assert 'フィールド名' in self.doc or '列名' in self.doc
        assert '出さない' in self.doc or '開示' in self.doc

    def test_instructs_leak_ban_covers_unenumerated_fields(self):
        """The ban on leaking field/column names is comprehensive, covering names
        not spelled out in the doc ("including anything not listed here") - not
        just the fields named explicitly. confidence/pattern used to be named here
        (a CSV column name actually leaked into user-facing text once), but as of
        2026-07-19 those two are dropped from the MCP response entirely (see
        server._strip_internal_advice_fields), so the leak they guarded against is
        now structurally impossible rather than merely instructed against."""
        assert '列挙されていない' in self.doc

