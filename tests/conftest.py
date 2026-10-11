"""Suite-wide guard: a real ANTHROPIC_API_KEY or OPENAI_API_KEY must never reach a test.

``stableagent.config.settings`` builds its ``Settings`` at import time, which would read the
developer's real key from ``.env``. ``pytest_configure`` runs before any test module is imported,
so putting a dummy key in the process environment first makes that import-time object hold the
dummy (environment variables take precedence over ``.env``). The autouse fixture then re-applies
the dummy through monkeypatch for every test, so a test that changes either channel cannot leak
into the next one. Tests that must run with no key at all request ``no_api_key`` (Anthropic) or
``no_openai_key``. The OpenAI key gets the same treatment as the Anthropic one.

The suite also turns off the seeding of a new default database from the shipped pilot database
(``STABLEAGENT_SEED_DB`` set to an empty string), so no test writes a database into the working
directory; the seeding tests set their own seed.
"""
from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

DUMMY_API_KEY = "test-anthropic-key-not-a-real-key"
DUMMY_OPENAI_API_KEY = "test-openai-key-not-a-real-key"
_ENV_VAR = "ANTHROPIC_API_KEY"
_OPENAI_ENV_VAR = "OPENAI_API_KEY"
_SEED_ENV_VAR = "STABLEAGENT_SEED_DB"
_GUARDED = (_ENV_VAR, _OPENAI_ENV_VAR, _SEED_ENV_VAR)
_previous_env_values: list[dict[str, str | None]] = []


def pytest_configure(config):
    _previous_env_values.append({name: os.environ.get(name) for name in _GUARDED})
    os.environ[_ENV_VAR] = DUMMY_API_KEY
    os.environ[_OPENAI_ENV_VAR] = DUMMY_OPENAI_API_KEY
    os.environ[_SEED_ENV_VAR] = ""


def pytest_unconfigure(config):
    previous = _previous_env_values.pop() if _previous_env_values else {}
    for name in _GUARDED:
        if previous.get(name) is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous[name]


@pytest.fixture(autouse=True)
def _dummy_api_key(monkeypatch):
    from stableagent.config.settings import settings

    monkeypatch.setenv(_ENV_VAR, DUMMY_API_KEY)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(DUMMY_API_KEY))
    monkeypatch.setenv(_OPENAI_ENV_VAR, DUMMY_OPENAI_API_KEY)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr(DUMMY_OPENAI_API_KEY))


@pytest.fixture()
def dummy_api_key() -> str:
    """The fake key every test runs with."""
    return DUMMY_API_KEY


@pytest.fixture()
def dummy_openai_api_key() -> str:
    """The fake OpenAI key every test runs with."""
    return DUMMY_OPENAI_API_KEY


@pytest.fixture()
def no_api_key(monkeypatch):
    """Run a test with no API key at all: env var unset and the settings value cleared."""
    from stableagent.config.settings import settings

    monkeypatch.delenv(_ENV_VAR, raising=False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)


@pytest.fixture()
def no_openai_key(monkeypatch):
    """Run a test with no OpenAI key at all: env var unset and the settings value cleared."""
    from stableagent.config.settings import settings

    monkeypatch.delenv(_OPENAI_ENV_VAR, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)


class NetworkAccessError(AssertionError):
    """An offline test tried to reach the network."""


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture()
def no_network(monkeypatch):
    """Fail on any DNS lookup or connection beyond loopback (asyncio's self-pipe uses loopback)."""
    import socket

    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] not in _LOOPBACK:
            raise NetworkAccessError(f"network connection attempted to {address!r}")
        return real_connect(self, address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if host not in _LOOPBACK and host is not None:
            raise NetworkAccessError(f"DNS lookup attempted for {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
