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


def test_openapi_declares_json_model_and_sse(client):
    content = client.get("/openapi.json").json()["paths"]["/v1/chat/completions"]["post"]["responses"]["200"]["content"]
    assert content["application/json"]["schema"] == {"$ref": "#/components/schemas/ChatCompletionResponse"}
    assert "text/event-stream" in content


@pytest.mark.parametrize("stop", ["two", ["zzz", "two"]])
def test_chat_stop_truncates_response(client, stop):
    body = _body(False)
    body["stop"] = stop
    resp = client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "line one\n\nline "


def test_chat_stop_truncates_stream(client):
    body = _body(True)
    body["stop"] = "two"
    resp = client.post("/v1/chat/completions", json=body)
    lines = [l[len("data: "):] for l in resp.text.split("\n\n") if l.startswith("data: ")]
    chunks = [json.loads(l) for l in lines[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "line one\n\nline "


def test_completion_stop_truncates_response(monkeypatch):
    async def fake_completion(request):
        return CONTENT

    monkeypatch.setattr(openai_compat.ai_service, "is_ppt_request", lambda text: False)
    monkeypatch.setattr(openai_compat.ai_service, "handle_general_completion_request", fake_completion)
    app = FastAPI()
    app.include_router(openai_compat.router, prefix="/v1")
    resp = TestClient(app).post(
        "/v1/completions", json={"model": "landppt-v1", "prompt": "hi", "stop": ["two"]}
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["text"] == "line one\n\nline "


@pytest.fixture
def completion_client(monkeypatch):
    async def fake_completion(request):
        return CONTENT

    monkeypatch.setattr(openai_compat.ai_service, "is_ppt_request", lambda text: False)
    monkeypatch.setattr(openai_compat.ai_service, "handle_general_completion_request", fake_completion)
    app = FastAPI()
    app.include_router(openai_compat.router, prefix="/v1")
    return TestClient(app)


def test_completion_stream_false_returns_json(completion_client):
    resp = completion_client.post(
        "/v1/completions", json={"model": "landppt-v1", "prompt": "hi", "stream": False}
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["text"] == CONTENT


def test_completion_stream_true_returns_sse(completion_client):
    resp = completion_client.post(
        "/v1/completions", json={"model": "landppt-v1", "prompt": "hi", "stream": True}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    lines = [l[len("data: "):] for l in resp.text.split("\n\n") if l.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(l) for l in lines[:-1]]
    assert all(c["object"] == "text_completion" for c in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert len({c["id"] for c in chunks}) == 1
    assert "".join(c["choices"][0]["text"] for c in chunks) == CONTENT


def test_completion_stream_respects_stop(completion_client):
    resp = completion_client.post(
        "/v1/completions",
        json={"model": "landppt-v1", "prompt": "hi", "stream": True, "stop": "two"},
    )
    lines = [l[len("data: "):] for l in resp.text.split("\n\n") if l.startswith("data: ")]
    chunks = [json.loads(l) for l in lines[:-1]]
    assert "".join(c["choices"][0]["text"] for c in chunks) == "line one\n\nline "
