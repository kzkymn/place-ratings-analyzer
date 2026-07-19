#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OAuth E2E connectivity client (manual integration test)

Connects to http://localhost:8888/mcp with OAuth as a real MCP client and
verifies the whole flow:
  1. OAuth metadata discovery + dynamic client registration (DCR)
  2. Open the Google consent screen in a browser (the only human step)
  3. Establish an MCP session with the issued token
  4. Run tools/list and place_ratings_analyze
"""

import asyncio
import sys

from fastmcp import Client

SERVER_URL = "http://localhost:8888/mcp"


async def main():
    # auth="oauth" starts the FastMCP client's OAuth flow.
    # The authorization URL is shown on stdout / opened in the browser.
    client = Client(SERVER_URL, auth="oauth")

    async with client:
        print("✅ OAuth 認証完了・MCP セッション確立", flush=True)

        tools = await client.list_tools()
        print(f"✅ tools/list: {[t.name for t in tools]}", flush=True)

        print("🔎 place_ratings_analyze('東京タワー') 実行中...", flush=True)
        result = await client.call_tool(
            "place_ratings_analyze", {"query": "東京タワー", "max_results": 1}
        )
        text = result.content[0].text if result.content else str(result)
        print("✅ ツール呼び出し成功。先頭 500 文字:", flush=True)
        print(text[:500], flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ E2E 失敗: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
