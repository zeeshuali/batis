"""Tests for /ai/* endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ai_status_is_reachable(client: AsyncClient):
    """GET /ai/status should always return 200 regardless of Ollama availability."""
    resp = await client.get("/ai/status")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ai_status_has_ollama_running_key(client: AsyncClient):
    """/ai/status response must include an 'ollama_running' boolean."""
    resp = await client.get("/ai/status")
    body = resp.json()
    assert "ollama_running" in body
    assert isinstance(body["ollama_running"], bool)


@pytest.mark.asyncio
async def test_ai_status_has_target_model_key(client: AsyncClient):
    resp = await client.get("/ai/status")
    body = resp.json()
    assert "target_model" in body
    assert isinstance(body["target_model"], str)


@pytest.mark.asyncio
async def test_ai_ask_missing_question_returns_400(client: AsyncClient):
    """POST /ai/ask with empty body should return 400."""
    resp = await client.post("/ai/ask", json={})
    assert resp.status_code == 400
    assert "question" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ai_ask_blank_question_returns_400(client: AsyncClient):
    """POST /ai/ask with whitespace-only question should return 400."""
    resp = await client.post("/ai/ask", json={"question": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_ai_ask_no_body_returns_error(client: AsyncClient):
    """POST /ai/ask with no JSON body at all should return 4xx."""
    resp = await client.post("/ai/ask")
    assert resp.status_code in (400, 422)
