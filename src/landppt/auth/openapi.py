"""Document middleware authentication without adding route-level auth side effects."""

from copy import copy
import hashlib
import re
from typing import Callable

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute


def install_auth_openapi(app: FastAPI, is_public_path: Callable[[str], bool]) -> None:
    app.openapi_schema = None

    def authenticated_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema

        routes = []
        seen_operations = set()
        used_ids = set()
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted(route.methods):
                operation = (route.path_format, method)
                if operation in seen_operations:
                    continue
                # Starlette dispatches the first registered matching handler.
                seen_operations.add(operation)
                if not route.include_in_schema:
                    continue
                documented = copy(route)
                documented.methods = {method}
                base_id = route.operation_id or (
                    re.sub(r"\W", "_", f"{route.name}{route.path_format}")
                    + f"_{method.lower()}"
                )
                if route.operation_id and len(route.methods) > 1:
                    base_id += f"_{method.lower()}"
                operation_id = base_id
                suffix = hashlib.sha256(
                    f"{method}:{route.path_format}".encode()
                ).hexdigest()[:12]
                counter = 0
                while operation_id in used_ids:
                    counter += 1
                    operation_id = f"{base_id}_{suffix}_{counter}"
                used_ids.add(operation_id)
                documented.operation_id = operation_id
                routes.append(documented)

        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            summary=app.summary,
            description=app.description,
            routes=routes,
            tags=app.openapi_tags,
            servers=app.servers,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
            separate_input_output_schemas=app.separate_input_output_schemas,
        )
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes.update(
            {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Personal LandPPT API key. Preferred for machine clients; inherits account permissions.",
                },
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
                "SessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "session_id",
                },
            }
        )
        for route in routes:
            method = next(iter(route.methods)).lower()
            operation = schema["paths"][route.path_format][method]
            if is_public_path(route.path):
                operation["security"] = []
            else:
                # Separate entries mean OR, never require all three credentials.
                operation["security"] = [
                    {"BearerAuth": []},
                    {"ApiKeyAuth": []},
                    {"SessionCookie": []},
                ]
                operation.setdefault("responses", {}).setdefault(
                    "401",
                    {
                        "description": "Authentication required or API key is invalid, expired or ambiguous.",
                    },
                )
        app.openapi_schema = schema
        return schema

    app.openapi = authenticated_openapi
