import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from landppt.api import openai_compat

CONTENT = "line one\n\nline two  with   spaces\n- item"


@pytest.fixture
def client(monkeypatch):
    async def fake_chat(request):
        return CONTENT

    monkeypatch.setattr(openai_compat.ai_service, "is_ppt_request", lambda text: False)
    monkeypatch.setattr(openai_compat.ai_service, "handle_general_chat_request", fake_chat)
    app = FastAPI()
    app.include_router(openai_compat.router, prefix="/v1")
    return TestClient(app)


def _body(stream):
    return {"model": "landppt-v1", "messages": [{"role": "user", "content": "hi"}], "stream": stream}


def test_stream_false_returns_json(client):
    resp = client.post("/v1/chat/completions", json=_body(False))
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == CONTENT


def test_stream_true_returns_sse(client):
    resp = client.post("/v1/chat/completions", json=_body(True))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    lines = [l[len("data: "):] for l in resp.text.split("\n\n") if l.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(l) for l in lines[:-1]]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert len({c["id"] for c in chunks}) == 1
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == CONTENT
