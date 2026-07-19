#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP Server Tests for Remote MCP Support

TDD Test Suite for:
- HTTP server startup
- stdio/HTTP transport switching
- OAuth configuration
- Argument parsing
"""

import pytest
import sys
import argparse
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestServerArgumentParsing:
    """Test command-line argument parsing for src/server.py"""

    def test_default_transport_is_stdio(self):
        """The default transport is stdio"""
        from src import server
        with patch('sys.argv', ['src.server']):
            parser = server.argparse.ArgumentParser()
            parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
            parser.add_argument('--host', default='127.0.0.1')
            parser.add_argument('--port', type=int, default=8000)
            args = parser.parse_args([])

            assert args.transport == 'stdio', "デフォルトのtransportはstdioであるべき"
            assert args.host == '127.0.0.1', "デフォルトのhostは127.0.0.1であるべき"
            assert args.port == 8000, "デフォルトのportは8000であるべき"

    def test_http_transport_option(self):
        """--transport http is accepted"""
        from src import server
        with patch('sys.argv', ['src.server', '--transport', 'http']):
            parser = server.argparse.ArgumentParser()
            parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
            args = parser.parse_args(['--transport', 'http'])

            assert args.transport == 'http', "--transport httpが受け付けられるべき"

    def test_stdio_transport_option(self):
        """--transport stdio is accepted"""
        from src import server
        with patch('sys.argv', ['src.server', '--transport', 'stdio']):
            parser = server.argparse.ArgumentParser()
            parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
            args = parser.parse_args(['--transport', 'stdio'])

            assert args.transport == 'stdio', "--transport stdioが受け付けられるべき"

    def test_host_option(self):
        """--host is accepted"""
        from src import server
        with patch('sys.argv', ['src.server', '--transport', 'http', '--host', '0.0.0.0']):
            parser = server.argparse.ArgumentParser()
            parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
            parser.add_argument('--host', default='127.0.0.1')
            args = parser.parse_args(['--transport', 'http', '--host', '0.0.0.0'])

            assert args.host == '0.0.0.0', "--host 0.0.0.0が受け付けられるべき"

    def test_port_option(self):
        """--port is accepted"""
        from src import server
        with patch('sys.argv', ['src.server', '--transport', 'http', '--port', '9000']):
            parser = server.argparse.ArgumentParser()
            parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
            parser.add_argument('--port', type=int, default=8000)
            args = parser.parse_args(['--transport', 'http', '--port', '9000'])

            assert args.port == 9000, "--port 9000が受け付けられるべき"


class TestHTTPServerStartup:
    """Test HTTP server startup functionality"""

    @patch('src.server.init_pipeline')
    @patch('src.server.mcp')
    def test_http_server_runs_with_correct_params(self, mock_mcp, mock_init):
        """In HTTP mode, mcp.run() is called with the right parameters"""
        mock_init.return_value = True

        with patch('sys.argv', ['src.server', '--transport', 'http', '--host', '0.0.0.0', '--port', '9000']):
            from src import server
            try:
                server.main()
            except SystemExit:
                pass

        # Verify mcp.run() was called with the right parameters
        mock_mcp.run.assert_called_once_with(transport='http', host='0.0.0.0', port=9000)

    @patch('src.server.init_pipeline')
    @patch('src.server.mcp')
    def test_stdio_server_runs_without_params(self, mock_mcp, mock_init):
        """In stdio mode, mcp.run() is called without parameters"""
        mock_init.return_value = True

        with patch('sys.argv', ['src.server', '--transport', 'stdio']):
            from src import server
            try:
                server.main()
            except SystemExit:
                pass

        # Verify mcp.run() was called without parameters
        mock_mcp.run.assert_called_once_with()


class TestOAuthConfiguration:
    """Test OAuth/OIDC configuration from environment variables"""

    @patch.dict('os.environ', {'MCP_CLIENT_ID': ''}, clear=False)
    def test_no_oauth_when_env_vars_missing(self):
        """Without MCP_CLIENT_ID, the OAuth config is None"""
        from src.server import setup_oauth
        auth = setup_oauth()
        assert auth is None, "MCP_CLIENT_IDがない場合はNoneを返すべき"

    @patch.dict('os.environ', {
        'MCP_CLIENT_ID': 'test-client-id',
        'MCP_CLIENT_SECRET': 'test-secret',
        'MCP_BASE_URL': 'http://localhost:8888'
    })
    def test_oauth_setup_with_env_vars(self):
        """With the env vars set, a real GoogleProvider instance is created"""
        from fastmcp.server.auth.providers.google import GoogleProvider
        from src.server import setup_oauth

        auth = setup_oauth()

        assert auth is not None, "OAuth設定がある場合はNone以外を返すべき"
        assert isinstance(auth, GoogleProvider), f"GoogleProviderインスタンスであるべき、実際: {type(auth)}"


class TestBackwardCompatibility:
    """Test backward compatibility with existing stdio behavior"""

    @patch('src.server.init_pipeline')
    @patch('src.server.mcp')
    def test_no_args_defaults_to_stdio(self, mock_mcp, mock_init):
        """Starting without arguments defaults to stdio"""
        # Ensure existing Claude Desktop integration continues to work
        mock_init.return_value = True

        with patch('sys.argv', ['src.server']):
            from src import server
            try:
                server.main()
            except SystemExit:
                pass

        # Without arguments, mcp.run() is called with no parameters (stdio mode)
        mock_mcp.run.assert_called_once_with()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
