"""Tests for the output caching module."""

import json
import time
from unittest.mock import patch

import pytest

from mcp_proxy.cache import (
    CachedOutputResponse,
    build_cached_output_payload,
    build_line_window_payload,
    clear_cache,
    create_cache_routes,
    create_cached_output,
    create_cached_output_with_meta,
    ensure_cache_dir,
    generate_token,
    retrieve_by_token,
    serialize_result,
    sign_url,
    verify_and_retrieve,
    verify_signature,
)


class TestCacheHelpers:
    """Tests for cache helper functions."""

    def test_ensure_cache_dir_creates_directory(self, tmp_path):
        """Test that ensure_cache_dir creates the directory."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path / "test-cache"):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path / "test-cache"
            result = ensure_cache_dir()
            assert result.exists()
            assert result.is_dir()

    def test_generate_token_returns_hex_string(self):
        """Test that generate_token returns a valid hex string."""
        token = generate_token()
        assert isinstance(token, str)
        assert len(token) == 32  # UUID hex is 32 chars
        int(token, 16)  # Should not raise

    def test_generate_token_is_unique(self):
        """Test that generate_token returns unique values."""
        tokens = [generate_token() for _ in range(100)]
        assert len(set(tokens)) == 100


class TestUrlSigning:
    """Tests for URL signing and verification."""

    def test_sign_url_returns_hex_signature(self):
        """Test that sign_url returns a valid hex signature."""
        sig = sign_url("token123", 1234567890, "secret")
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex is 64 chars

    def test_sign_url_is_deterministic(self):
        """Test that sign_url returns the same signature for same inputs."""
        sig1 = sign_url("token", 12345, "secret")
        sig2 = sign_url("token", 12345, "secret")
        assert sig1 == sig2

    def test_sign_url_differs_with_different_inputs(self):
        """Test that sign_url returns different signatures for different inputs."""
        sig1 = sign_url("token1", 12345, "secret")
        sig2 = sign_url("token2", 12345, "secret")
        sig3 = sign_url("token1", 12346, "secret")
        sig4 = sign_url("token1", 12345, "secret2")
        assert len({sig1, sig2, sig3, sig4}) == 4

    def test_verify_signature_valid(self):
        """Test that verify_signature returns True for valid signature."""
        sig = sign_url("token", 12345, "secret")
        assert verify_signature("token", 12345, sig, "secret") is True

    def test_verify_signature_invalid(self):
        """Test that verify_signature returns False for invalid signature."""
        assert verify_signature("token", 12345, "invalid", "secret") is False


class TestSerializeResult:
    """Tests for result serialization."""

    def test_serialize_string(self):
        """Test serializing a string."""
        assert serialize_result("hello") == "hello"

    def test_serialize_dict(self):
        """Test serializing a dict."""
        result = serialize_result({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_serialize_list(self):
        """Test serializing a list."""
        result = serialize_result([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_serialize_object_with_default_str(self):
        """Test serializing an object using default=str fallback."""

        class CustomObj:
            def __str__(self):
                return "custom"

        # json.dumps with default=str converts the object to string
        result = serialize_result(CustomObj())
        # json.dumps wraps the string in quotes
        assert result == '"custom"'

    def test_serialize_with_circular_reference(self):
        """Test serializing an object with circular reference falls back to str."""
        from unittest.mock import patch

        # Mock json.dumps to raise ValueError (simulating circular reference)
        with patch("mcp_proxy.cache.json.dumps", side_effect=ValueError("Circular")):
            result = serialize_result({"key": "value"})
            # Falls back to str() representation
            assert "key" in result


class TestBuildLineWindowPayload:
    """Tests for configurable cached-output line windows."""

    def test_builds_line_window(self):
        """Test building a bounded line window."""
        result = build_line_window_payload(
            "line 1\nline 2\nline 3\nline 4",
            line_offset=1,
            line_count=2,
        )

        assert result == {
            "content": "line 2\nline 3",
            "line_offset": 1,
            "line_count": 2,
            "returned_lines": 2,
            "total_lines": 4,
            "next_line_offset": 3,
            "truncated": True,
        }

    def test_builds_tail_window_without_line_count(self):
        """Test building a line window from an offset to the end."""
        result = build_line_window_payload("a\nb\nc", line_offset=1)

        assert result == {
            "content": "b\nc",
            "line_offset": 1,
            "line_count": None,
            "returned_lines": 2,
            "total_lines": 3,
            "next_line_offset": None,
            "truncated": False,
        }

    def test_rejects_negative_line_offset(self):
        """Test that negative line offsets are rejected."""
        with pytest.raises(ValueError, match="line_offset"):
            build_line_window_payload("a\nb", line_offset=-1)

    def test_rejects_negative_line_count(self):
        """Test that negative line counts are rejected."""
        with pytest.raises(ValueError, match="line_count"):
            build_line_window_payload("a\nb", line_count=-1)


class TestBuildCachedOutputPayload:
    """Tests for cached-output retrieval payloads."""

    def test_returns_full_content_by_default(self):
        """Test default payload returns full content for compatibility."""
        assert build_cached_output_payload("full content") == {
            "content": "full content"
        }

    def test_returns_line_window(self):
        """Test payload can return a configurable line window."""
        result = build_cached_output_payload(
            "first\nsecond\nthird",
            line_offset=1,
            line_count=1,
        )

        assert result["content"] == "second"
        assert result["line_offset"] == 1
        assert result["line_count"] == 1
        assert result["returned_lines"] == 1
        assert result["total_lines"] == 3
        assert result["next_line_offset"] == 2
        assert result["truncated"] is True

    def test_returns_error_for_invalid_line_window(self):
        """Test invalid line windows return structured errors."""
        result = build_cached_output_payload("first\nsecond", line_offset=-1)

        assert result == {"error": "line_offset must be >= 0"}

    def test_applies_jmespath_expression(self):
        """Test JMESPath extracts a JSON subset."""
        content = json.dumps({"items": [{"title": "A"}, {"title": "B"}]})

        result = build_cached_output_payload(
            content,
            jmespath_expression="items[].title",
        )

        assert json.loads(result["content"]) == ["A", "B"]
        assert result["jmespath_expression"] == "items[].title"

    def test_applies_line_window_to_jmespath_result(self):
        """Test line windows can slice serialized JMESPath results."""
        content = json.dumps({"items": [{"title": "A"}, {"title": "B"}]})

        result = build_cached_output_payload(
            content,
            line_count=2,
            jmespath_expression="items",
        )

        assert result["content"] == "[\n  {"
        assert result["jmespath_expression"] == "items"
        assert result["truncated"] is True

    def test_returns_error_for_non_json_jmespath_content(self):
        """Test JMESPath requires JSON cached output."""
        result = build_cached_output_payload(
            "not json",
            jmespath_expression="items",
        )

        assert result == {"error": "Cached output is not valid JSON"}

    def test_returns_error_for_invalid_jmespath(self):
        """Test invalid JMESPath expressions return structured errors."""
        result = build_cached_output_payload(
            '{"items": []}',
            jmespath_expression="items[",
        )

        assert result["error"].startswith("Invalid JMESPath expression:")


class TestCreateCachedOutput:
    """Tests for create_cached_output function."""

    def test_creates_cache_file(self, tmp_path):
        """Test that create_cached_output creates a cache file."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output(
                content="test content",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )
            cache_file = tmp_path / f"{response.token}.txt"
            assert cache_file.exists()
            assert cache_file.read_text() == "test content"

    def test_returns_cached_output_response(self, tmp_path):
        """Test that create_cached_output returns proper response."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output(
                content="test content",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )
            assert isinstance(response, CachedOutputResponse)
            assert response.cached is True
            assert response.token
            assert "http://localhost:8000/cache/" in response.retrieve_url
            assert response.preview == "test content"
            assert response.size_bytes == len("test content".encode())

    def test_preview_truncation(self, tmp_path):
        """Test that preview is truncated for long content."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            long_content = "x" * 1000
            response = create_cached_output(
                content=long_content,
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )
            assert len(response.preview) == 103  # 100 + "..."
            assert response.preview.endswith("...")


class TestCreateCachedOutputWithMeta:
    """Tests for create_cached_output_with_meta function."""

    def test_creates_meta_file(self, tmp_path):
        """Test that create_cached_output_with_meta creates a meta file."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output_with_meta(
                content="test content",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )
            meta_file = tmp_path / f"{response.token}.meta"
            assert meta_file.exists()
            meta = json.loads(meta_file.read_text())
            assert "expires_at" in meta
            assert "signature" in meta


class TestVerifyAndRetrieve:
    """Tests for verify_and_retrieve function."""

    def test_retrieves_valid_content(self, tmp_path):
        """Test retrieving valid cached content."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            # Create a cache file
            token = "testtoken123"
            expires_at = int(time.time()) + 3600
            signature = sign_url(token, expires_at, "secret")
            (tmp_path / f"{token}.txt").write_text("cached content")

            result = verify_and_retrieve(token, expires_at, signature, "secret")
            assert result == "cached content"

    def test_returns_none_for_invalid_signature(self, tmp_path):
        """Test that invalid signature returns None."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            token = "testtoken123"
            expires_at = int(time.time()) + 3600
            (tmp_path / f"{token}.txt").write_text("cached content")

            result = verify_and_retrieve(token, expires_at, "invalid", "secret")
            assert result is None

    def test_returns_none_for_expired_url(self, tmp_path):
        """Test that expired URL returns None."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            token = "testtoken123"
            expires_at = int(time.time()) - 100  # Expired
            signature = sign_url(token, expires_at, "secret")
            (tmp_path / f"{token}.txt").write_text("cached content")

            result = verify_and_retrieve(token, expires_at, signature, "secret")
            assert result is None

    def test_returns_none_for_missing_file(self, tmp_path):
        """Test that missing file returns None."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            token = "nonexistent"
            expires_at = int(time.time()) + 3600
            signature = sign_url(token, expires_at, "secret")

            result = verify_and_retrieve(token, expires_at, signature, "secret")
            assert result is None


class TestRetrieveByToken:
    """Tests for retrieve_by_token function."""

    def test_retrieves_with_token_only(self, tmp_path):
        """Test retrieving content using only the token."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            # Create cache with meta
            response = create_cached_output_with_meta(
                content="test content",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            result = retrieve_by_token(response.token, "secret")
            assert result == "test content"

    def test_returns_none_for_missing_meta(self, tmp_path):
        """Test that missing meta file returns None."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            result = retrieve_by_token("nonexistent", "secret")
            assert result is None

    def test_returns_none_for_invalid_meta(self, tmp_path):
        """Test that invalid meta file returns None."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            (tmp_path / "badtoken.meta").write_text("not json")
            result = retrieve_by_token("badtoken", "secret")
            assert result is None


class TestClearCache:
    """Tests for clear_cache function."""

    def test_clears_all_files(self, tmp_path):
        """Test that clear_cache removes all files."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            # Create some files
            (tmp_path / "file1.txt").write_text("content1")
            (tmp_path / "file2.txt").write_text("content2")
            (tmp_path / "file3.meta").write_text("{}")

            count = clear_cache()
            assert count == 3
            assert list(tmp_path.iterdir()) == []

    def test_returns_zero_for_empty_cache(self, tmp_path):
        """Test that clear_cache returns 0 for empty cache."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            count = clear_cache()
            assert count == 0

    def test_returns_zero_for_nonexistent_dir(self, tmp_path):
        """Test that clear_cache returns 0 for nonexistent directory."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path / "nonexistent"):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path / "nonexistent"
            count = clear_cache()
            assert count == 0

    def test_skips_directories(self, tmp_path):
        """Test that clear_cache skips directories."""
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            # Create a file and a directory
            (tmp_path / "file1.txt").write_text("content1")
            (tmp_path / "subdir").mkdir()

            count = clear_cache()
            # Only the file should be deleted
            assert count == 1
            # Directory should still exist
            assert (tmp_path / "subdir").exists()


class TestCacheRoutes:
    """Tests for cache HTTP routes."""

    @pytest.mark.asyncio
    async def test_retrieve_cache_success(self, tmp_path):
        """Test successful cache retrieval via HTTP."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            # Create cached content
            response = create_cached_output_with_meta(
                content="http test content",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            # Create routes and test
            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            # Extract query params from URL
            url_parts = response.retrieve_url.split("?")
            query = url_parts[1]
            http_response = client.get(f"/cache/{response.token}?{query}")
            assert http_response.status_code == 200
            assert http_response.text == "http test content"

    @pytest.mark.asyncio
    async def test_retrieve_cache_line_window(self, tmp_path):
        """Test cache retrieval can return a line window via HTTP."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output_with_meta(
                content="first\nsecond\nthird",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            query = response.retrieve_url.split("?")[1]
            http_response = client.get(
                f"/cache/{response.token}?{query}&line_offset=1&line_count=1"
            )
            assert http_response.status_code == 200
            assert http_response.text == "second"

    @pytest.mark.asyncio
    async def test_retrieve_cache_jmespath_expression(self, tmp_path):
        """Test cache retrieval can apply a JMESPath expression via HTTP."""
        from urllib.parse import urlencode

        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output_with_meta(
                content=json.dumps({"items": [{"title": "A"}, {"title": "B"}]}),
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            signed_query = response.retrieve_url.split("?")[1]
            filter_query = urlencode({"jmespath": "items[].title"})
            http_response = client.get(
                f"/cache/{response.token}?{signed_query}&{filter_query}"
            )
            assert http_response.status_code == 200
            assert json.loads(http_response.text) == ["A", "B"]

    @pytest.mark.asyncio
    async def test_retrieve_cache_invalid_line_count(self, tmp_path):
        """Test invalid line_count query parameters return 400."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output_with_meta(
                content="first\nsecond",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            query = response.retrieve_url.split("?")[1]
            http_response = client.get(
                f"/cache/{response.token}?{query}&line_count=bad"
            )
            assert http_response.status_code == 400
            assert http_response.text == "Invalid line_count parameter"

    @pytest.mark.asyncio
    async def test_retrieve_cache_invalid_jmespath_content(self, tmp_path):
        """Test JMESPath errors return 400 via HTTP."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            response = create_cached_output_with_meta(
                content="not json",
                secret="secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            query = response.retrieve_url.split("?")[1]
            http_response = client.get(
                f"/cache/{response.token}?{query}&jmespath_expression=items"
            )
            assert http_response.status_code == 400
            assert http_response.text == "Cached output is not valid JSON"

    @pytest.mark.asyncio
    async def test_retrieve_cache_missing_params(self, tmp_path):
        """Test cache retrieval with missing parameters."""
        from starlette.testclient import TestClient

        routes = create_cache_routes("secret")
        from starlette.applications import Starlette

        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/cache/sometoken")
        assert response.status_code == 400
        assert "Missing" in response.text

    @pytest.mark.asyncio
    async def test_retrieve_cache_invalid_expires(self, tmp_path):
        """Test cache retrieval with invalid expires parameter."""
        from starlette.testclient import TestClient

        routes = create_cache_routes("secret")
        from starlette.applications import Starlette

        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/cache/sometoken?expires=notanumber&sig=abc")
        assert response.status_code == 400
        assert "Invalid" in response.text

    @pytest.mark.asyncio
    async def test_retrieve_cache_not_found(self, tmp_path):
        """Test cache retrieval for non-existent token."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            expires = int(time.time()) + 3600
            sig = sign_url("nonexistent", expires, "secret")
            response = client.get(f"/cache/nonexistent?expires={expires}&sig={sig}")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retrieve_cache_tampered_signature(self, tmp_path):
        """Test cache retrieval rejects tampered signatures."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Create valid cached content
            response = create_cached_output_with_meta(
                "secret content", "secret", "http://test", 3600, 100
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            # Try with tampered signature
            expires = int(time.time()) + 3600
            http_response = client.get(
                f"/cache/{response.token}?expires={expires}&sig=tampered_signature"
            )
            assert http_response.status_code == 404
            assert "invalid signature" in http_response.text.lower()

    @pytest.mark.asyncio
    async def test_retrieve_cache_expired_url(self, tmp_path):
        """Test cache retrieval rejects expired URLs."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Create valid cached content
            response = create_cached_output_with_meta(
                "secret content", "secret", "http://test", 3600, 100
            )

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            # Create signature for expired timestamp
            expired_time = int(time.time()) - 100  # 100 seconds ago
            expired_sig = sign_url(response.token, expired_time, "secret")
            http_response = client.get(
                f"/cache/{response.token}?expires={expired_time}&sig={expired_sig}"
            )
            assert http_response.status_code == 404

    @pytest.mark.asyncio
    async def test_retrieve_cache_wrong_secret(self, tmp_path):
        """Test cache retrieval rejects signatures made with wrong secret."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Create cached content with one secret
            response = create_cached_output_with_meta(
                "secret content", "correct_secret", "http://test", 3600, 100
            )

            # Server uses different secret
            routes = create_cache_routes("different_secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            # Use URL generated with original secret
            url_parts = response.retrieve_url.split("?")
            query = url_parts[1]
            http_response = client.get(f"/cache/{response.token}?{query}")
            assert http_response.status_code == 404

    @pytest.mark.asyncio
    async def test_retrieve_cache_path_traversal_rejected(self, tmp_path):
        """Test cache retrieval rejects path traversal attempts."""
        from starlette.testclient import TestClient

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            routes = create_cache_routes("secret")
            from starlette.applications import Starlette

            app = Starlette(routes=routes)
            client = TestClient(app)

            # Try path traversal attacks
            malicious_tokens = [
                "../etc/passwd",
                "..%2F..%2Fetc%2Fpasswd",
                "....//....//etc/passwd",
                "/etc/passwd",
                "token/../../../etc/passwd",
            ]

            for token in malicious_tokens:
                expires = int(time.time()) + 3600
                sig = sign_url(token, expires, "secret")
                # URL encode the token for the request
                import urllib.parse

                encoded_token = urllib.parse.quote(token, safe="")
                http_response = client.get(
                    f"/cache/{encoded_token}?expires={expires}&sig={sig}"
                )
                # Should either 404 (not found) or fail - never return /etc/passwd
                assert http_response.status_code in (404, 400, 422)
                assert "root:" not in http_response.text  # /etc/passwd content
