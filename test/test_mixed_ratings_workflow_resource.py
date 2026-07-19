#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for exposing the mixed-ratings workflow as an MCP resource
(place-ratings-analyzer://mixed-ratings-workflow).

Background: the "🔧 応用" section of data/mcp_tool_descriptions/place_ratings_analyze.md
used to get injected into every place_ratings_analyze call, including ones unrelated
to finding places with divided ratings, so it was split into its own file published as
an MCP resource. Plain MCP resources are application-driven (the host decides whether
to read them) and the LLM has no path to read them on its own, so the ResourcesAsTools
transform also exposes read_resource / list_resources as regular tools, letting the
LLM read them proactively on any client.
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import Client
from src import server

WORKFLOW_FILE = (
    Path(__file__).parent.parent / 'data' / 'mcp_tool_descriptions' / 'mixed_ratings_workflow.md'
)
DESCRIPTION_FILE = (
    Path(__file__).parent.parent / 'data' / 'mcp_tool_descriptions' / 'place_ratings_analyze.md'
)


class TestMixedRatingsWorkflowResourceFile(unittest.TestCase):
    """Verify the content of the new file (mixed_ratings_workflow.md) itself"""

    def setUp(self):
        self.assertTrue(WORKFLOW_FILE.exists(), f"{WORKFLOW_FILE} が存在しません")
        self.doc = WORKFLOW_FILE.read_text(encoding='utf-8')

    def test_contains_step_by_step_workflow(self):
        self.assertIn('食べログ', self.doc)
        self.assertIn('手順', self.doc)
        self.assertIn('SrtT=rt', self.doc)

    def test_contains_chain_store_exclusion_note(self):
        self.assertIn('チェーン店', self.doc)

    def test_contains_external_site_access_failure_note(self):
        self.assertIn('アクセスが失敗した場合', self.doc)

    def test_instructs_how_to_frame_the_result_for_the_user(self):
        """The document frames result presentation as a positive instruction.

        Background: because this workflow's purpose is finding places with divided
        ratings, the LLM tends to wrap up with a verdict that names a real place
        ("the place with the bad reputation is X"). Negative prohibitions ("don't
        make verdicts") don't land well with LLMs, so instead the document states
        the action to take: present them as places that need verification."""
        self.assertIn('確認が必要な店', self.doc)

    def test_instructs_the_llm_to_describe_findings_in_its_own_words(self):
        """The document instructs the LLM to describe each place in its own words.

        Background: the rationale wording of step 4's candidate filtering (e.g. "the
        low ratings are likely an impression shared by a certain number of users")
        was copied verbatim into user-facing answers as verdicts about individual
        places. This document is a candidate-narrowing procedure, not a supply of
        per-place commentary."""
        self.assertIn('自身の言葉', self.doc)

    def test_threshold_is_a_placeholder_not_a_hardcoded_percent(self):
        """The star-1(+2) ratio threshold is injected from config.json; the file itself
        holds only a placeholder (hardcoding the number here would make it
        unadjustable via the config file)."""
        self.assertIn('__THRESHOLD_PERCENT__', self.doc)

    def test_instructs_that_low_rating_causes_may_no_longer_apply(self):
        """The document instructs conveying that low-rating causes may be resolved by
        now, or may come down to taste or price range rather than flaws, and the
        situation may no longer be the same.

        Background: cases were observed where the LLM introduced real places (a
        budget cake shop reputed to be "cheap and nothing more", a restaurant with
        early operational issues that may have since improved) with a definitive
        "better avoid" framing. Conveying not just the low-rating reasons as
        confirmed facts but also the caveat that they may no longer hold prevents
        definitive avoidance recommendations."""
        marker = '結果をユーザーへ提示するとき'
        self.assertIn(marker, self.doc)
        presentation_section = self.doc.split(marker, 1)[1]
        self.assertIn('限らない', presentation_section)


class TestSearchGoogleMapsDescriptionNoLongerContainsWorkflow(unittest.TestCase):
    """The 🔧応用 body has been moved out of place_ratings_analyze.md, and the doc
    explicitly points to reading it via the read_resource tool"""

    def setUp(self):
        self.doc = server._PLACE_RATINGS_ANALYZE_DESCRIPTION
        self.assertEqual(self.doc, DESCRIPTION_FILE.read_text(encoding='utf-8'))

    def test_does_not_contain_moved_step_details(self):
        self.assertNotIn('SrtT=rt', self.doc)
        self.assertNotIn('アクセスが失敗した場合', self.doc)

    def test_points_to_resource_uri_via_read_resource_tool(self):
        self.assertIn('place-ratings-analyzer://mixed-ratings-workflow', self.doc)
        self.assertIn('read_resource', self.doc)


class TestMixedRatingsWorkflowResourceRegistration(unittest.IsolatedAsyncioTestCase):
    """The place-ratings-analyzer://mixed-ratings-workflow resource is registered on
    the MCP server and readable through the read_resource tool via ResourcesAsTools
    (no Go binary involved, so verify with an in-process Client, no subprocess)"""

    async def test_resource_readable_directly(self):
        expected = WORKFLOW_FILE.read_text(encoding='utf-8').replace(
            '__THRESHOLD_PERCENT__', str(server._MIXED_RATINGS_THRESHOLD_PERCENT)
        )
        async with Client(server.mcp) as client:
            result = await client.read_resource("place-ratings-analyzer://mixed-ratings-workflow")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].text, expected)

    async def test_resource_threshold_matches_config(self):
        """config.json's mixed_ratings_workflow.star1_plus_star2_threshold_percent is
        reflected in the actually served document (no placeholder left)."""
        async with Client(server.mcp) as client:
            result = await client.read_resource("place-ratings-analyzer://mixed-ratings-workflow")
            text = result[0].text
            self.assertNotIn('__THRESHOLD_PERCENT__', text)
            self.assertIn(f'{server._MIXED_RATINGS_THRESHOLD_PERCENT}%超', text)

    async def test_read_resource_tool_exposes_workflow(self):
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}
            self.assertIn('read_resource', tool_names)
            self.assertIn('list_resources', tool_names)

            response = await client.call_tool(
                'read_resource', {'uri': 'place-ratings-analyzer://mixed-ratings-workflow'}
            )
            text = response.content[0].text
            self.assertIn('食べログ', text)


if __name__ == '__main__':
    unittest.main()
