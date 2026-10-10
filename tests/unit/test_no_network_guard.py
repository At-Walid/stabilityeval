"""The ``no_network`` fixture (tests/conftest.py) really blocks network access."""
from __future__ import annotations

import socket
import urllib.request

import pytest


def test_dns_lookups_and_connections_fail(no_network):
    with pytest.raises(AssertionError, match="DNS lookup attempted for 'api.anthropic.com'"):
        socket.getaddrinfo("api.anthropic.com", 443)
    with pytest.raises(AssertionError, match="network connection attempted"):
        with socket.socket() as sock:
            sock.connect(("203.0.113.1", 443))
    with pytest.raises(AssertionError, match="DNS lookup attempted for 'huggingface.co'"):
        urllib.request.urlopen("https://huggingface.co/datasets", timeout=1)


def test_loopback_stays_available(no_network):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.socket() as client:
            client.connect(server.getsockname())
