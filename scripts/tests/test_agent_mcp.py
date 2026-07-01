#!/usr/bin/env python3
# Unit tests for agent_mcp helpers, including the vault path-escape guard.
# agent_mcp imports the `mcp` package, so this module is skipped where mcp is
# not installed (e.g. a minimal local env) and runs in CI.

import os
import struct
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.fastmcp")

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
os.environ.setdefault("AGENT_VAULT_DIR", "/tmp/aoa-vault-test")
import agent_mcp as A  # noqa: E402


def test_vault_path_rejects_escapes():
    # Directory traversal and absolute paths must not resolve inside the vault.
    assert A._safe_vault_path("../../etc/passwd") is None
    assert A._safe_vault_path("/etc/passwd") is None
    assert A._safe_vault_path("../secrets.env") is None


def test_vault_path_accepts_valid():
    p = A._safe_vault_path("journal/2026-01-01.md")
    assert p is not None
    assert str(p).startswith(str(A.VAULT.resolve()))


def test_cosine_identity_and_orthogonal():
    assert abs(A._cosine([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9
    assert abs(A._cosine([1, 0, 0], [0, 1, 0]) - 0.0) < 1e-9
    assert A._cosine([0, 0, 0], [1, 1, 1]) == 0.0  # zero vector guard


def test_unpack_embedding_roundtrip():
    vals = [0.1, -0.2, 0.3, 0.9]
    out = A._unpack_embedding(struct.pack("4f", *vals))
    assert len(out) == 4
    assert abs(out[0] - 0.1) < 1e-6
    assert abs(out[1] + 0.2) < 1e-6


def test_default_provider_is_openai():
    import models as M
    assert "openai.com" in M.CHAT_URL
    assert M.API_KEY_ENV == "OPENAI_API_KEY"
    assert M.FLAGSHIP.startswith("gpt-")
