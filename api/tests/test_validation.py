"""Unit tests for agent endpoint URL validation."""

from unittest.mock import patch, MagicMock
import pytest

from api.validation import validate_agent_endpoint


def test_valid_url():
    """Valid http/https URLs should pass."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve, \
         patch("api.validation.httpx.Client") as mock_client:
        mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_head = MagicMock()
        mock_head.status_code = 200
        mock_client.return_value.__enter__.return_value.head.return_value = mock_head

        valid, msg = validate_agent_endpoint("https://example.com/api")
        assert valid, f"Expected valid, got: {msg}"


def test_invalid_format():
    """Non-http URLs should be rejected."""
    valid, msg = validate_agent_endpoint("ftp://example.com")
    assert not valid
    assert "http" in msg.lower()


def test_empty_url():
    """Empty or None URLs should be rejected."""
    valid, msg = validate_agent_endpoint("")
    assert not valid
    assert "required" in msg.lower()


def test_whitespace_only():
    """Whitespace-only URLs should be rejected."""
    valid, msg = validate_agent_endpoint("   ")
    assert not valid
    assert "required" in msg.lower()


def test_localhost_blocked():
    """localhost should be blocked (SSRF protection)."""
    valid, msg = validate_agent_endpoint("http://localhost:8000")
    assert not valid
    assert "SSRF" in msg or "localhost" in msg


def test_loopback_127_blocked():
    """127.x.x.x should be blocked."""
    valid, msg = validate_agent_endpoint("http://127.0.0.1:8000/api")
    assert not valid
    assert "blocked" in msg.lower() or "SSRF" in msg


def test_private_ip_blocked():
    """192.168.x.x should be blocked."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve:
        mock_resolve.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]
        valid, msg = validate_agent_endpoint("http://internal.corp/api")
        assert not valid
        assert "SSRF" in msg or "private" in msg


def test_private_10_blocked():
    """10.x.x.x should be blocked."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve:
        mock_resolve.return_value = [(2, 1, 6, "", ("10.0.0.5", 80))]
        valid, msg = validate_agent_endpoint("http://internal-10.example.com/api")
        assert not valid
        assert "SSRF" in msg or "private" in msg


def test_timeout():
    """Unreachable endpoints should time out gracefully."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve, \
         patch("api.validation.httpx.Client") as mock_client:
        mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_client.return_value.__enter__.return_value.head.side_effect = \
            __import__("httpx").TimeoutException("timeout")

        valid, msg = validate_agent_endpoint("https://unreachable.example.com")
        assert not valid
        assert "timeout" in msg.lower()


def test_connect_error():
    """Connection refused should be caught."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve, \
         patch("api.validation.httpx.Client") as mock_client:
        mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_client.return_value.__enter__.return_value.head.side_effect = \
            __import__("httpx").ConnectError("Connection refused")

        valid, msg = validate_agent_endpoint("https://refused.example.com")
        assert not valid
        assert "connect" in msg.lower()


def test_server_error():
    """HTTP 5xx should be rejected."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve, \
         patch("api.validation.httpx.Client") as mock_client:
        mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_head = MagicMock()
        mock_head.status_code = 502
        mock_client.return_value.__enter__.return_value.head.return_value = mock_head

        valid, msg = validate_agent_endpoint("https://error.example.com/api")
        assert not valid
        assert "502" in msg


def test_https_accepted():
    """HTTPS URLs should be accepted."""
    with patch("api.validation.socket.getaddrinfo") as mock_resolve, \
         patch("api.validation.httpx.Client") as mock_client:
        mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_head = MagicMock()
        mock_head.status_code = 200
        mock_client.return_value.__enter__.return_value.head.return_value = mock_head

        valid, msg = validate_agent_endpoint("https://secure.example.com/agent")
        assert valid, f"Expected valid, got: {msg}"