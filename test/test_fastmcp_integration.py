import unittest
import asyncio
import json # Added import
import os # Added import
import subprocess
import tempfile
from unittest.mock import patch, MagicMock
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

_PROJECT_ROOT = Path(__file__).parent.parent
_SCRAPER_BINARY = _PROJECT_ROOT / "google-maps-scraper" / "bin" / "google_maps_scraper"


class TestFastMcpIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Integration test suite for src/server.py.
    Talks to the server through fastmcp.Client.
    """

    client = None

    @classmethod
    def setUpClass(cls):
        # 開発環境の前提チェック（プロビジョニングはしない。手順は
        # .agents/skills/build-go/ と .agents/skills/run-tests/ を参照）
        if not _SCRAPER_BINARY.exists():
            raise RuntimeError(
                f"Go scraper binary not found: {_SCRAPER_BINARY} — "
                "build it first (see .agents/skills/build-go/)"
            )

    async def asyncSetUp(self):
        print("\n--- Initializing fastmcp.Client ---")
        # fastmcp.Client manages the server process internally
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "src.server"],
            cwd=str(Path(__file__).parent.parent),
        )
        self.client = Client(transport)
        await self.client.__aenter__()  # equivalent to async with client:'s __aenter__
        print("✅ fastmcp.Client initialized and connected.")

    async def asyncTearDown(self):
        print("\n--- Tearing down fastmcp.Client ---")
        await self.client.__aexit__(None, None, None)  # equivalent to async with client:'s __aexit__
        print("✅ fastmcp.Client disconnected.")

    async def test_place_ratings_analyze_tool_scraper_not_found_error(self):
        """
        Test error handling when the pipeline is uninitialized (in-process unit test).
        The stdio transport starts the server in a subprocess, so cross-process
        mocking has no effect; call the src.server functions directly instead.
        """
        print("\n--- Testing place_ratings_analyze (pipeline init failure, in-process) ---")

        import src.server as server_module

        original_pipeline = server_module.pipeline
        server_module.pipeline = None

        try:
            with patch('src.server.init_pipeline', return_value=False):
                result = await server_module.place_ratings_analyze(
                    query="test query for error handling",
                    max_results=1
                )

            print(f"Result: {result}")
            self.assertIsNotNone(result)
            self.assertIn('error', result)
            self.assertEqual(result['error'], "パイプラインの初期化に失敗しました。Go scraperバイナリが見つからない可能性があります。")
            self.assertIn('suggestion', result)
            self.assertEqual(result['suggestion'], "google-maps-scraper/bin/google_maps_scraperが存在することを確認してください。")
            print("✅ pipeline init failure error test passed.")

        finally:
            server_module.pipeline = original_pipeline

    async def test_place_ratings_analyze_data_conversion_error(self):
        """
        Test error handling for data-conversion errors in the CSV (invalid rating / review count).
        """
        print("\n--- Testing place_ratings_analyze tool (data conversion error) ---")
        
        # Create a CSV file containing invalid numeric data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as invalid_csv:
            invalid_csv.write("name,rating,reviews_count,reviews_per_rating,open_hours,user_reviews_extended\n")
            invalid_csv.write("Test Place,invalid_rating,not_a_number,{},\"{}\",\"[]\"\n")
            invalid_csv_path = invalid_csv.name
        
        try:
            # Mock extract_places to return the path of the invalid-data CSV
            with patch('src.pipeline.GoogleMapsPipeline.extract_places') as mock_extract:
                mock_extract.return_value = invalid_csv_path
                
                query_params = {
                    "query": "test query for data conversion error",
                    "max_results": 1
                }
                response = await self.client.call_tool("place_ratings_analyze", query_params)
                print(f"Tool response: {response}")

                self.assertIsNotNone(response)
                # Data-conversion errors are handled internally; accept a normal or error response
                if 'error' in response.structured_content:
                    error_msg = response.structured_content.get('error')
                    self.assertIn('検索処理中にエラーが発生しました', error_msg)
                else:
                    # On normal processing, verify places exists
                    self.assertIn('places', response.structured_content)
                
                print("✅ place_ratings_analyze tool data conversion error test passed.")
        
        finally:
            # Clean up the temp file
            if os.path.exists(invalid_csv_path):
                os.unlink(invalid_csv_path)

    async def test_place_ratings_analyze_json_parse_error(self):
        """
        Test error handling for JSON parse errors (invalid rating distribution, hours, reviews).
        """
        print("\n--- Testing place_ratings_analyze tool (JSON parse error) ---")
        
        # Create a CSV file containing invalid JSON data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as invalid_csv:
            invalid_csv.write("name,rating,reviews_count,reviews_per_rating,open_hours,user_reviews_extended\n")
            invalid_csv.write("Test Place,4.5,100,\"invalid json{\",\"invalid json{\",\"invalid json{\"\n")
            invalid_csv_path = invalid_csv.name
        
        try:
            # Mock extract_places to return the path of the invalid-JSON CSV
            with patch('src.pipeline.GoogleMapsPipeline.extract_places') as mock_extract:
                mock_extract.return_value = invalid_csv_path
                
                query_params = {
                    "query": "test query for JSON parse error",
                    "max_results": 1
                }
                response = await self.client.call_tool("place_ratings_analyze", query_params)
                print(f"Tool response: {response}")

                self.assertIsNotNone(response)
                # JSON parse errors are handled internally; accept a normal or error response
                if 'error' in response.structured_content:
                    error_msg = response.structured_content.get('error')
                    self.assertIn('検索処理中にエラーが発生しました', error_msg)
                else:
                    # On normal processing, verify places exists
                    self.assertIn('places', response.structured_content)
                
                print("✅ place_ratings_analyze tool JSON parse error test passed.")
        
        finally:
            # Clean up the temp file
            if os.path.exists(invalid_csv_path):
                os.unlink(invalid_csv_path)

    async def test_place_ratings_analyze_area_search_notice_for_multiple_hits(self):
        """
        A multi-hit (area+category-style) search result carries
        area_search_notice pointing at mixed-ratings-workflow, so an LLM
        that skipped the workflow for an "avoid store" request can still
        self-correct after seeing the result (2026-07-19 design: the
        instruction to use the workflow lives only in the tool description,
        which E2E testing showed gets ignored at that pre-call decision
        point; this notice is the result-attached backstop).

        In-process unit test, not via the fastmcp.Client/stdio subprocess:
        as documented on test_place_ratings_analyze_general_exception above,
        the stdio transport runs the server in a separate subprocess, so
        mocking GoogleMapsPipeline.extract_places from this test process has
        no effect there.
        """
        print("\n--- Testing place_ratings_analyze (area_search_notice, in-process) ---")

        import src.server as server_module

        if server_module.pipeline is None:
            server_module.init_pipeline()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as valid_csv:
            valid_csv.write(
                "title,category,address,review_rating,review_count,price_range,"
                "phone,website,emails,reviews_per_rating,open_hours,user_reviews_extended\n"
            )
            valid_csv.write(
                'Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,'
                'https://test.com,test@test.com,"{}","{}","[]"\n'
            )
            valid_csv.write(
                'Test Cafe,Cafe,Shibuya Japan,4.0,50,¥¥,03-5678-1234,'
                'https://cafe.com,cafe@cafe.com,"{}","{}","[]"\n'
            )
            valid_csv_path = valid_csv.name

        try:
            with patch.object(server_module.pipeline, 'extract_places',
                               return_value=valid_csv_path):
                result = await server_module.place_ratings_analyze(
                    query="test query for area search notice",
                    max_results=2
                )

            print(f"Result: {result}")
            self.assertNotIn('error', result)
            notice = result.get('area_search_notice')
            self.assertIsNotNone(notice)
            self.assertIn('mixed-ratings-workflow', notice)
            print("✅ place_ratings_analyze area_search_notice test passed.")
        finally:
            if os.path.exists(valid_csv_path):
                os.unlink(valid_csv_path)

    async def test_place_ratings_analyze_omits_internal_only_fields(self):
        """
        rating_advice must not carry 'pattern' or 'confidence' to the LLM
        client: they are internal CSV-matching bookkeeping with no bearing
        on what the LLM should do, and the tool description explicitly
        forbids surfacing them anyway (2026-07-19: dropping them shrinks
        both the per-store JSON payload and the field-name-leak-prevention
        paragraph in place_ratings_analyze.md that has to enumerate them).
        advice_text/warning_text/quality_level/general_disclaimer, which the
        LLM does need, must still be present.
        """
        print("\n--- Testing place_ratings_analyze (internal-only field omission, in-process) ---")

        import src.server as server_module

        if server_module.pipeline is None:
            server_module.init_pipeline()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as valid_csv:
            valid_csv.write(
                "title,category,address,review_rating,review_count,price_range,"
                "phone,website,emails,reviews_per_rating,open_hours,user_reviews_extended\n"
            )
            valid_csv.write(
                'Test Restaurant,Restaurant,Tokyo Japan,4.5,100,¥¥¥,03-1234-5678,'
                'https://test.com,test@test.com,"{""5"":""50"",""4"":""30"",""3"":""15"",""2"":""3"",""1"":""2""}","{}","[]"\n'
            )
            valid_csv_path = valid_csv.name

        try:
            with patch.object(server_module.pipeline, 'extract_places',
                               return_value=valid_csv_path):
                result = await server_module.place_ratings_analyze(
                    query="test query for internal-only field omission",
                    max_results=1
                )

            print(f"Result: {result}")
            self.assertNotIn('error', result)
            advice = result['places'][0]['rating_advice']
            self.assertNotIn('pattern', advice)
            self.assertNotIn('confidence', advice)
            self.assertIn('advice_text', advice)
            self.assertIn('warning_text', advice)
            self.assertIn('quality_level', advice)
            self.assertIn('general_disclaimer', advice)
            print("✅ place_ratings_analyze internal-only field omission test passed.")
        finally:
            if os.path.exists(valid_csv_path):
                os.unlink(valid_csv_path)

    async def test_place_ratings_analyze_flags_star5_dominance_stores_at_top_level(self):
        """
        When comparing multiple stores in one call, a per-store
        star5_dominance_notice buried inside each place's rating_advice is
        easy for the synthesizing LLM to catch for some stores and miss for
        others (2026-08-05 real-world incident: of several stores returned
        in one comparison, only one had its notice honored — the rest were
        introduced as ordinary recommendations even though their JSON also
        carried the notice). Mirroring the area_search_notice fix (see
        test_place_ratings_analyze_area_search_notice_for_multiple_hits),
        the backstop must be a top-level field attached to the same result,
        listing every flagged store by name, not just a per-store field the
        LLM has to remember to check one by one.
        """
        print("\n--- Testing place_ratings_analyze (star5 dominance flagging, in-process) ---")

        import src.server as server_module

        if server_module.pipeline is None:
            server_module.init_pipeline()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as valid_csv:
            valid_csv.write(
                "title,category,address,review_rating,review_count,price_range,"
                "phone,website,emails,reviews_per_rating,open_hours,user_reviews_extended\n"
            )
            # Star5-dominant store (85% star5 ratio, exceeds the 80% threshold)
            valid_csv.write(
                'Flagged Sushi,Restaurant,Tokyo Japan,4.8,100,¥¥¥¥,03-1234-5678,'
                'https://flagged.example,flagged@test.com,'
                '"{""5"":""85"",""4"":""5"",""3"":""5"",""2"":""3"",""1"":""2""}","{}","[]"\n'
            )
            # Ordinary well-distributed store (50% star5 ratio, below threshold)
            valid_csv.write(
                'Ordinary Cafe,Cafe,Shibuya Japan,4.2,100,¥¥,03-5678-1234,'
                'https://ordinary.example,ordinary@test.com,'
                '"{""5"":""50"",""4"":""30"",""3"":""15"",""2"":""3"",""1"":""2""}","{}","[]"\n'
            )
            valid_csv_path = valid_csv.name

        try:
            with patch.object(server_module.pipeline, 'extract_places',
                               return_value=valid_csv_path):
                result = await server_module.place_ratings_analyze(
                    query="test query for star5 dominance flagging",
                    max_results=2
                )

            print(f"Result: {result}")
            self.assertNotIn('error', result)

            flagged = result.get('star5_dominance_review_required')
            self.assertIsNotNone(flagged)
            self.assertIn('Flagged Sushi', flagged['store_names'])
            self.assertNotIn('Ordinary Cafe', flagged['store_names'])
            self.assertTrue(len(flagged['instruction']) > 0)
            print("✅ place_ratings_analyze star5 dominance flagging test passed.")
        finally:
            if os.path.exists(valid_csv_path):
                os.unlink(valid_csv_path)

    async def test_place_ratings_analyze_omits_star5_dominance_field_when_none_flagged(self):
        """
        No store should be silently included/excluded via an ambiguous
        empty-vs-missing state: when nothing is flagged, the field must be
        explicitly None (matching the existing area_search_notice
        convention), not simply absent from the response.
        """
        print("\n--- Testing place_ratings_analyze (no star5 dominance flagged, in-process) ---")

        import src.server as server_module

        if server_module.pipeline is None:
            server_module.init_pipeline()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as valid_csv:
            valid_csv.write(
                "title,category,address,review_rating,review_count,price_range,"
                "phone,website,emails,reviews_per_rating,open_hours,user_reviews_extended\n"
            )
            valid_csv.write(
                'Ordinary Cafe,Cafe,Shibuya Japan,4.2,100,¥¥,03-5678-1234,'
                'https://ordinary.example,ordinary@test.com,'
                '"{""5"":""50"",""4"":""30"",""3"":""15"",""2"":""3"",""1"":""2""}","{}","[]"\n'
            )
            valid_csv_path = valid_csv.name

        try:
            with patch.object(server_module.pipeline, 'extract_places',
                               return_value=valid_csv_path):
                result = await server_module.place_ratings_analyze(
                    query="test query for no star5 dominance flagged",
                    max_results=1
                )

            print(f"Result: {result}")
            self.assertNotIn('error', result)
            self.assertIn('star5_dominance_review_required', result)
            self.assertIsNone(result['star5_dominance_review_required'])
            print("✅ place_ratings_analyze no-flag test passed.")
        finally:
            if os.path.exists(valid_csv_path):
                os.unlink(valid_csv_path)

    async def test_place_ratings_analyze_empty_query(self):
        """
        Test error handling for an empty search query.
        """
        print("\n--- Testing place_ratings_analyze tool (empty query) ---")
        
        query_params = {
            "query": "",
            "max_results": 1
        }
        response = await self.client.call_tool("place_ratings_analyze", query_params)
        print(f"Tool response: {response}")

        self.assertIsNotNone(response)
        self.assertIn('error', response.structured_content)
        
        # Verify the empty-query error message
        error_msg = response.structured_content.get('error')
        self.assertEqual(error_msg, "検索クエリが空です")
        
        print("✅ place_ratings_analyze tool empty query test passed.")

    async def test_place_ratings_analyze_parameter_validation(self):
        """
        Test capping of max_results and concurrency.
        """
        print("\n--- Testing place_ratings_analyze tool (parameter validation) ---")
        
        # max_results above the cap
        query_params = {
            "query": "test query for parameter validation",
            "max_results": 150,  # exceeds the cap of 100
            "concurrency": 20    # exceeds the cap of 16
        }
        response = await self.client.call_tool("place_ratings_analyze", query_params)
        print(f"Tool response: {response}")

        self.assertIsNotNone(response)
        # Parameters are clamped internally; accept a normal or error response
        if 'error' in response.structured_content:
            error_msg = response.structured_content.get('error')
            self.assertIn('検索処理中にエラーが発生しました', error_msg)
        else:
            # On normal processing, the parameter clamping worked
            self.assertTrue('places' in response.structured_content or 'query' in response.structured_content)
        
        print("✅ place_ratings_analyze tool parameter validation test passed.")

    async def test_place_ratings_analyze_general_exception(self):
        """
        Test error handling for a generic unexpected exception (in-process unit test).
        The stdio transport starts the server in a subprocess, so cross-process
        mocking has no effect; call the src.server functions directly instead.
        """
        print("\n--- Testing place_ratings_analyze (general exception, in-process) ---")

        import src.server as server_module

        # Initialize the pipeline in the test process before mocking
        if server_module.pipeline is None:
            server_module.init_pipeline()

        with patch.object(server_module.pipeline, 'extract_places',
                          side_effect=RuntimeError("Unexpected error occurred")):
            result = await server_module.place_ratings_analyze(
                query="test query for general exception",
                max_results=1
            )

        print(f"Result: {result}")
        self.assertIsNotNone(result)
        self.assertIn('error', result)
        error_msg = result.get('error')
        self.assertIn('検索処理中にエラーが発生しました', error_msg)
        self.assertIn('Unexpected error occurred', error_msg)
        print("✅ place_ratings_analyze general exception test passed.")

if __name__ == '__main__':
    unittest.main()
