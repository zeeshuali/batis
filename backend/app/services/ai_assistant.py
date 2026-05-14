"""
RAG + Ollama query pipeline — Phase 2.

Flow:
  1. Embed the user question with all-MiniLM-L6-v2 (same model as embed.py)
  2. pgvector cosine similarity search in ai_embeddings → top-k context chunks
  3. Build a system + user prompt with the retrieved context
  4. POST to local Ollama /api/generate (Llama 3.2 11B)
  5. Return the answer + source snippets
"""
from __future__ import annotations

import httpx
from sqlalchemy import text
from typing import Any, Dict, List

from app.core.config import get_settings
from ml.embed import _embed  # reuse the same model instance

TOP_K = 6
MAX_CONTEXT_CHARS = 4000


def _get_ollama_url() -> str:
    return get_settings().ollama_url


def _get_ollama_model() -> str:
    return get_settings().ollama_model


def _retrieve_context(conn, question: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
    """Vector similarity search — returns top-k content chunks."""
    embedding = _embed([question])[0]
    # Use CAST(:emb AS vector) with a bound parameter — never interpolate vectors into SQL strings
    rows = conn.execute(
        text("""
        SELECT
            content_type,
            content_id,
            content_text,
            1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        FROM ai_embeddings
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :k
        """),
        {"emb": str(embedding), "k": top_k},
    ).mappings().all()
    return [dict(r) for r in rows]


def _build_prompt(question: str, context_chunks: List[Dict[str, Any]]) -> str:
    """Assemble the context block and user question into a single prompt string."""
    ctx_lines = []
    total = 0
    for chunk in context_chunks:
        line = f"[{chunk['content_type']} {chunk['content_id']}] {chunk['content_text']}"
        if total + len(line) > MAX_CONTEXT_CHARS:
            break
        ctx_lines.append(line)
        total += len(line)

    context_block = "\n".join(ctx_lines)

    return (
        "You are an expert transit analyst for the San Francisco Bay Area, "
        "covering all 511.org agencies (AC Transit, Muni, BART, Caltrain, VTA, "
        "Golden Gate, SamTrans, WETA, etc.). Each context chunk is tagged with "
        "the originating agency. Answer questions using only the provided "
        "context and call out which agency a finding refers to when relevant. "
        "Be concise and specific. If the context does not contain enough "
        "information to answer, say so clearly.\n\n"
        f"CONTEXT:\n{context_block}\n\n"
        f"QUESTION: {question}\n\n"
        "ANSWER:"
    )


def ask(conn, question: str, top_k: int = TOP_K) -> Dict[str, Any]:
    """
    Full RAG pipeline: embed → retrieve → prompt → generate.

    Returns:
        {
            "answer": str,
            "sources": [{"content_type": ..., "content_id": ..., "similarity": ...}],
            "model": str,
        }
    """
    ollama_url = _get_ollama_url()
    ollama_model = _get_ollama_model()

    chunks = _retrieve_context(conn, question, top_k)
    prompt = _build_prompt(question, chunks)

    try:
        resp = httpx.post(
            f"{ollama_url}/api/generate",
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 512,
                },
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
    except httpx.ConnectError:
        answer = (
            "The local AI model is not running. "
            f"Please start Ollama with: ollama serve && ollama pull {ollama_model}"
        )
    except Exception as exc:
        answer = f"Error calling local model: {exc}"

    return {
        "answer": answer,
        "sources": [
            {
                "content_type": c["content_type"],
                "content_id": c["content_id"],
                "similarity": round(float(c["similarity"]), 4),
                "snippet": c["content_text"][:200],
            }
            for c in chunks
        ],
        "model": ollama_model,
    }


def explain_route(conn, route_id: str) -> Dict[str, Any]:
    """Generate a natural language summary for a specific route.

    After Phase 3 the embedding pipeline writes route content_ids as
    '{agency_id}:{route_id}' to disambiguate cross-agency collisions
    (SF + SC both use '31'). Match both the new composite form and the
    legacy plain route_id so the endpoint continues to work pre/post
    embed re-run; if multiple agencies match, returns the first.
    """
    question = (
        f"Give a concise performance summary for transit route {route_id}. "
        "Include average delay, on-time percentage, and any notable issues."
    )
    # Narrow the context to this route first. Composite-id rows look
    # like '{agency}:{route_id}'; legacy rows are just route_id.
    rows = conn.execute(
        text("""
        SELECT content_text
        FROM ai_embeddings
        WHERE content_type = 'route'
          AND (content_id = :rid OR content_id LIKE '%:' || :rid)
        LIMIT 1
        """),
        {"rid": route_id},
    ).mappings().all()

    if not rows:
        return {
            "route_id": route_id,
            "summary": f"No embedding data found for route {route_id}. "
                       "The embedding pipeline may not have run yet.",
            "model": OLLAMA_MODEL,
        }

    # Use full RAG but seed with route-specific context
    result = ask(conn, question)
    result["route_id"] = route_id
    return result


def get_status() -> Dict[str, Any]:
    """Check Ollama connectivity and list available models."""
    ollama_url = _get_ollama_url()
    ollama_model = _get_ollama_model()
    try:
        resp = httpx.get(f"{ollama_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        target_ready = any(ollama_model in m for m in models)
        return {
            "ollama_running": True,
            "available_models": models,
            "target_model": ollama_model,
            "target_ready": target_ready,
        }
    except httpx.ConnectError:
        return {
            "ollama_running": False,
            "available_models": [],
            "target_model": ollama_model,
            "target_ready": False,
            "hint": f"Run: ollama serve && ollama pull {ollama_model}",
        }
    except Exception as exc:
        return {
            "ollama_running": False,
            "available_models": [],
            "target_model": ollama_model,
            "target_ready": False,
            "error": str(exc),
        }
