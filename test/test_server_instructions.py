#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests that server-level MCP instructions are set.

Background: MCP clients (Claude Desktop etc.) lazy-load MCP tools. By default the
LLM has not read any tool descriptions; it decides "should I go look at this
server?" from the one server-level line. If that reads as nothing more than
"Google Maps (place search)", it is treated as identical to the client's built-in
place search and the tool descriptions never get a chance to be read.
(Measured: no amount of tool name/description improvement got it selected.)

Hence FastMCP's instructions carry the server's reason to exist. The text is not
inlined in Python source; it is loaded from
data/mcp_tool_descriptions/server_instructions.md (same external-file policy as
rating_messages.json and the tool descriptions).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import server

INSTRUCTIONS_FILE = (
    Path(__file__).parent.parent / 'data' / 'mcp_tool_descriptions' / 'server_instructions.md'
)


class TestServerInstructions:
    """Verify the FastMCP server's instructions"""

    def test_instructions_are_set_on_the_server(self):
        """instructions are set (unset means nothing reaches the client)"""
        assert server.mcp.instructions
        assert len(server.mcp.instructions.strip()) > 0

    def test_instructions_are_loaded_verbatim_from_external_file(self):
        """The instructions' source of truth is the external file, not inlined in Python source"""
        assert server.mcp.instructions == INSTRUCTIONS_FILE.read_text(encoding='utf-8')

    def test_covers_flip_follow_up_to_a_prior_recommendation_ask(self):
        """A follow-up asking the opposite of a prior "recommend" ask (e.g. "which
        would you NOT recommend?") must trigger the mixed-ratings-workflow resource
        too, not just a standalone "low rated places" request - otherwise the LLM
        answers from already-fetched, popularity-biased category-search data."""
        assert '逆に' in server.mcp.instructions
        assert '直前に' in server.mcp.instructions
