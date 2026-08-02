#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps FastMCP Server

Run as a module from the project root: python -m src.server [--transport http]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.transforms import ResourcesAsTools

load_dotenv()

from .pipeline import GoogleMapsPipeline, load_json_config

# Define scraper binary path
_project_root = Path(__file__).parent.parent
_scraper_binary_path = _project_root / "google-maps-scraper" / "bin" / "google_maps_scraper"

_MIXED_RATINGS_WORKFLOW_DEFAULTS = {
    "mixed_ratings_workflow": {"star1_plus_star2_threshold_percent": 15}
}


def _load_tool_description(filename: str) -> str:
    """
    Load an MCP tool description from data/mcp_tool_descriptions/
    (long texts are kept in external files instead of inline in Python source)

    Args:
        filename: file name under data/mcp_tool_descriptions/

    Returns:
        The file's content (string)

    Raises:
        FileNotFoundError: if the file does not exist
    """
    path = _project_root / "data" / "mcp_tool_descriptions" / filename
    if not path.exists():
        raise FileNotFoundError(f"MCPツール説明ファイルが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


_PLACE_RATINGS_ANALYZE_DESCRIPTION = _load_tool_description("place_ratings_analyze.md")

_mixed_ratings_config = load_json_config(
    _project_root / "config.json", _MIXED_RATINGS_WORKFLOW_DEFAULTS
)
_MIXED_RATINGS_THRESHOLD_PERCENT = (
    _mixed_ratings_config["mixed_ratings_workflow"]["star1_plus_star2_threshold_percent"]
)
_MIXED_RATINGS_WORKFLOW_CONTENT = _load_tool_description("mixed_ratings_workflow.md").replace(
    "__THRESHOLD_PERCENT__", str(_MIXED_RATINGS_THRESHOLD_PERCENT)
)

# MCP clients lazy-load tools, so by default the LLM has not read any tool
# descriptions. What gets read at the "should I go look at this server?" stage is
# this server-level instructions text; improving tool names or descriptions only
# takes effect after that decision (confirmed empirically).
_SERVER_INSTRUCTIONS = _load_tool_description("server_instructions.md")


def setup_oauth() -> Optional[object]:
    """
    Build OAuth configuration from environment variables (FastMCP GoogleProvider)

    Required environment variables:
    - MCP_CLIENT_ID: Google OAuth Client ID
    - MCP_CLIENT_SECRET: Google OAuth Client Secret
    - MCP_BASE_URL: base URL of the HTTP server (e.g. http://localhost:8888)

    Requires fastmcp>=2.12.0.
    Details: https://gofastmcp.com/integrations/google

    Returns:
        A GoogleProvider instance, or None when credentials are absent
    """
    client_id = os.getenv("MCP_CLIENT_ID")
    client_secret = os.getenv("MCP_CLIENT_SECRET")
    base_url = os.getenv("MCP_BASE_URL")

    if not client_id:
        return None  # no authentication

    if not client_secret:
        print("⚠️  MCP_CLIENT_SECRETが設定されていません。認証なしで起動します。", file=sys.stderr)
        return None

    if not base_url:
        print("⚠️  MCP_BASE_URLが設定されていません。認証なしで起動します。", file=sys.stderr)
        return None

    try:
        from fastmcp.server.auth.providers.google import GoogleProvider

        print(f"🔐 Google OAuth認証を有効化", file=sys.stderr)
        print(f"   Client ID: {client_id}", file=sys.stderr)
        print(f"   Base URL: {base_url}", file=sys.stderr)

        return GoogleProvider(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            required_scopes=[
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
            ]
        )
    except ImportError as e:
        print(f"⚠️  GoogleProvider が利用できません: {e}", file=sys.stderr)
        print("   fastmcp>=2.12.0 が必要です。pip install 'fastmcp>=2.12.0'", file=sys.stderr)
        print("   認証なしで起動します。", file=sys.stderr)
        return None
    except Exception as e:
        print(f"⚠️  OAuth設定エラー: {e}", file=sys.stderr)
        print("   認証なしで起動します。", file=sys.stderr)
        return None


_auth = setup_oauth()

mcp = FastMCP(
    "place-ratings-analyzer",
    instructions=_SERVER_INSTRUCTIONS,
    auth=_auth if _auth else None,
)

# MCP resources are application-driven (the host decides whether to read them), so
# the LLM has no path to read them on its own. Expose read_resource/list_resources
# as regular tools too, so the LLM can read them proactively on any client.
mcp.add_transform(ResourcesAsTools(mcp))

# Global pipeline instance
pipeline = None

def init_pipeline():
    """Initialize the pipeline"""
    global pipeline
    # Race-condition guard: wait for the Go binary build to finish
    for attempt in range(3):
        try:
            pipeline = GoogleMapsPipeline(scraper_path=str(_scraper_binary_path))
            print("✅ パイプライン初期化成功", file=sys.stderr)
            return True
        except FileNotFoundError:
            print(f"⏳ パイプライン初期化待機中... ({attempt + 1}/3)", file=sys.stderr)
            time.sleep(0.1)  # wait 100ms

    print(f"❌ パイプライン初期化エラー: 3回試行後もGo scraperが見つかりません。", file=sys.stderr)
    return False


_INTERNAL_ONLY_ADVICE_FIELDS = ('pattern', 'confidence')


def _strip_internal_advice_fields(place: Dict[str, Any]) -> Dict[str, Any]:
    """Drop internal-only rating_advice fields before a place crosses into the MCP response"""
    if not place.get('rating_advice'):
        return place
    place = dict(place)
    place['rating_advice'] = {
        key: value for key, value in place['rating_advice'].items()
        if key not in _INTERNAL_ONLY_ADVICE_FIELDS
    }
    return place


@mcp.tool(description=_PLACE_RATINGS_ANALYZE_DESCRIPTION)
async def place_ratings_analyze(
    query: str,
    max_results: int = 20,
    concurrency: int = 8,
    detailed_info: bool = True
) -> Dict[str, Any]:
    """The actual description handed to MCP clients / AI agents lives in
    data/mcp_tool_descriptions/place_ratings_analyze.md."""
    global pipeline

    # Pipeline initialization check
    if pipeline is None and not init_pipeline():
        return {
            "error": "パイプラインの初期化に失敗しました。Go scraperバイナリが見つからない可能性があります。",
            "suggestion": "google-maps-scraper/bin/google_maps_scraperが存在することを確認してください。"
        }
    
    # Parameter validation
    if not query.strip():
        return {"error": "検索クエリが空です"}
    
    if max_results > 100:
        max_results = 100
        
    if concurrency > 16:
        concurrency = 16
    
    try:
        # Run the end-to-end pipeline
        print(f"🔍 Google Maps検索開始: '{query}'", file=sys.stderr)

        csv_file = pipeline.extract_places(
            query=query,
            max_results=max_results,
            concurrency=concurrency
        )
        results = pipeline.analyze_results(csv_file, detailed_info=detailed_info)

        # pattern/confidence are internal CSV-matching bookkeeping with no
        # bearing on what the LLM should do, and the tool description already
        # forbids surfacing them - dropping them here shrinks both the
        # per-store JSON payload and that prohibition's field list.
        places_for_llm = [_strip_internal_advice_fields(place) for place in results['places'][:10]]

        # Format for MCP
        return {
            "success": True,
            "query": query,
            "total_places": results['total_places'],
            "summary": results['summary'],
            "places": places_for_llm,  # first 10 only (response size limit)
            "full_results_count": len(results['places']),
            "area_search_notice": results['area_search_notice']
        }

    except Exception as e:
        return {
            "error": f"検索処理中にエラーが発生しました: {str(e)}",
            "query": query
        }

@mcp.resource("place-ratings-analyzer://mixed-ratings-workflow")
async def get_mixed_ratings_workflow() -> str:
    """評価の割れる店探しワークフローの詳細手順を返します"""
    return _MIXED_RATINGS_WORKFLOW_CONTENT


@mcp.resource("place-ratings-analyzer://status")
async def get_server_status() -> str:
    """MCPサーバーの状態を返します"""
    global pipeline
    
    status = {
        "server": "Google Maps MCP Server",
        "version": "1.0.0",
        "pipeline_initialized": pipeline is not None,
        "available_tools": [
            "place_ratings_analyze"
        ]
    }

    return json.dumps(status, ensure_ascii=False, indent=2)


def main():
    """Server startup logic"""
    parser = argparse.ArgumentParser(
        description="Google Maps MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # stdio mode (default, for Claude Desktop)
  python -m src.server

  # HTTP mode (for remote MCP)
  python -m src.server --transport http
  python -m src.server --transport http --host 0.0.0.0 --port 9000
        """
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type: stdio (default) or http"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (HTTP mode only, default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port to bind (HTTP mode only, default: 8000, or $PORT if set — Cloud Run injects this)"
    )
    args = parser.parse_args()

    print("🚀 Google Maps FastMCP Server 起動中...", file=sys.stderr)
    sys.stderr.flush()

    # Initialize the pipeline
    if init_pipeline():
        print("✅ パイプライン初期化完了", file=sys.stderr)
    else:
        print("⚠️  パイプライン初期化に失敗しましたが、サーバーを起動します", file=sys.stderr)
    sys.stderr.flush()

    # Start the MCP server
    if args.transport == "http":
        print(f"🌐 HTTPサーバーモード: http://{args.host}:{args.port}/mcp", file=sys.stderr)
        sys.stderr.flush()
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        print("🎯 stdioサーバーモード起動完了", file=sys.stderr)
        sys.stderr.flush()
        mcp.run()


if __name__ == "__main__":
    main()
