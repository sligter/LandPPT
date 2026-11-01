"""Machine clients see authentication and the same handler as runtime dispatch."""

import warnings

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from landppt.auth.middleware import AuthMiddleware
from landppt.auth.openapi import install_auth_openapi


def test_schema_documents_alternative_auth_and_leaves_public_routes_public():
    app = FastAPI()
    policy = AuthMiddleware()

    async def handler():
        return {"ok": True}

    paths = [
        "/api/projects",
        "/projects/{project_id}/confirm-requirements",
        "/v1/models",
        "/health",
        "/api/auth/login",
        "/api/share/{token}/slides-data",
    ]
    for path in paths:
        app.add_api_route(path, handler)
    install_auth_openapi(app, policy.is_public_path)
    schema = app.openapi()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert schemes["ApiKeyAuth"]["name"] == "X-API-Key"
    assert schemes["SessionCookie"]["in"] == "cookie"
    for path in paths:
        operation = schema["paths"][path]["get"]
        if policy.is_public_path(path):
            assert operation["security"] == []
        else:
            assert operation["security"] == [
                {"BearerAuth": []},
                {"ApiKeyAuth": []},
                {"SessionCookie": []},
            ]
            assert "401" in operation["responses"]
    assert app.openapi() is schema


def test_schema_uses_first_registered_duplicate_route_and_unique_ids():
    app = FastAPI()

    class FirstResult(BaseModel):
        first: bool

    class UnreachableResult(BaseModel):
        second: bool

    async def first():
        return {"first": True}

    async def second():
        return {"second": True}

    app.add_api_route(
        "/api/duplicate", first, response_model=FirstResult, operation_id="shared"
    )
    app.add_api_route(
        "/api/duplicate",
        second,
        response_model=UnreachableResult,
        operation_id="shared",
    )
    app.add_api_route(
        "/api/multiple", first, methods=["GET", "HEAD"], operation_id="shared"
    )
    app.add_api_route("/api/other", first, operation_id="shared")
    install_auth_openapi(app, AuthMiddleware().is_public_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        schema = app.openapi()
    operations = [op for path in schema["paths"].values() for op in path.values()]
    ids = [op["operationId"] for op in operations]
    assert len(ids) == len(set(ids)) == 4
    result_schema = schema["paths"]["/api/duplicate"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert result_schema["$ref"].endswith("/FirstResult")
    assert "UnreachableResult" not in schema["components"]["schemas"]
    assert TestClient(app).get("/api/duplicate").json() == {"first": True}
    # Schema generation must not mutate runtime routes.
    assert (
        len([r for r in app.routes if getattr(r, "path", "") == "/api/duplicate"]) == 2
    )
    assert next(
        r for r in app.routes if getattr(r, "path", "") == "/api/multiple"
    ).methods == {"GET", "HEAD"}


def test_hidden_first_handler_is_not_replaced_by_unreachable_schema_entry():
    app = FastAPI()

    async def hidden():
        return "hidden"

    app.add_api_route("/api/hidden", hidden, include_in_schema=False)
    app.add_api_route("/api/hidden", hidden)
    install_auth_openapi(app, AuthMiddleware().is_public_path)
    assert "/api/hidden" not in app.openapi()["paths"]
