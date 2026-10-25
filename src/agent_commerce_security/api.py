"""Small local WSGI API for the step 3 demo."""

from __future__ import annotations

import json
from typing import Callable

from .commerce import CommerceService, SecurityError

MAX_BODY_BYTES = 4_096


class DemoAPI:
    def __init__(self, commerce: CommerceService, catalog_items: list[dict]):
        self.commerce = commerce
        self.catalog_items = catalog_items

    def __call__(self, environ: dict, start_response: Callable) -> list[bytes]:
        try:
            method = environ.get("REQUEST_METHOD")
            path = environ.get("PATH_INFO")
            if method == "GET" and path == "/health":
                return self._respond(start_response, "200 OK", {"status": "ok"})
            token = self._bearer(environ.get("HTTP_AUTHORIZATION"))
            if method == "GET" and path == "/v1/catalog":
                principal = self.commerce.principal(token, "catalog:read")
                self.commerce.audit_decision("client", "list_services", "allow", "OK",
                                             tenant_id=principal.tenant_id, user_id=principal.user_id)
                items = [{"item_id": item["item_id"], "source_id": item["source_id"],
                          "free_facts": item["free_facts"], "trust": "untrusted_catalog_data"}
                         for item in self.catalog_items]
                return self._respond(start_response, "200 OK", {"items": items})
            if method == "POST" and path == "/v1/quotes":
                body = self._body(environ, {"service_id"})
                return self._respond(start_response, "201 Created", self.commerce.quote(token, body["service_id"]))
            if method == "POST" and path == "/v1/purchases":
                body = self._body(environ, {"quote_id", "request_id"})
                receipt = self.commerce.purchase(token, body["quote_id"], body["request_id"])
                return self._respond(start_response, "200 OK" if receipt["idempotent_replay"] else "201 Created", receipt)
            return self._respond(start_response, "404 Not Found", {"error": "NOT_FOUND"})
        except SecurityError as error:
            if path == "/v1/catalog" or error.code == "REQUEST_SCHEMA_DENIED":
                try:
                    self.commerce.audit_decision("client", "list_services" if path == "/v1/catalog" else path,
                                                 "deny", error.code)
                except Exception:
                    return self._respond(start_response, "503 Service Unavailable", {"error": "AUDIT_UNAVAILABLE"})
            if error.code == "TOKEN_INVALID":
                status = "401 Unauthorized"
            elif error.code in {"REQUEST_SCHEMA_DENIED", "PURCHASE_SCHEMA_DENIED"}:
                status = "400 Bad Request"
            elif error.code.endswith("_DENIED") or error.code in {"USER_INACTIVE", "SELLER_BLOCKED"}:
                status = "403 Forbidden"
            elif error.code in {"SERVICE_UNAVAILABLE", "QUOTE_NOT_FOUND"}:
                status = "404 Not Found"
            else:
                status = "409 Conflict"
            return self._respond(start_response, status, {"error": error.code})
        except Exception:
            return self._respond(start_response, "503 Service Unavailable", {"error": "STORE_UNAVAILABLE"})

    @staticmethod
    def _bearer(value: str | None) -> str:
        if type(value) is not str or not value.startswith("Bearer ") or value.count(" ") != 1:
            raise SecurityError("TOKEN_INVALID")
        return value[7:]

    @staticmethod
    def _body(environ: dict, expected: set[str]) -> dict:
        try:
            if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("JSON content type required")
            length = int(environ.get("CONTENT_LENGTH", ""))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("invalid body size")
            raw = environ["wsgi.input"].read(length)
            if len(raw) != length:
                raise ValueError("truncated body")
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = value
                return result

            body = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(body, dict) or set(body) != expected or any(type(value) is not str for value in body.values()):
                raise ValueError("invalid body schema")
            return body
        except (ValueError, KeyError, UnicodeError) as error:
            raise SecurityError("REQUEST_SCHEMA_DENIED") from error

    @staticmethod
    def _respond(start_response: Callable, status: str, result: dict) -> list[bytes]:
        body = json.dumps(result, separators=(",", ":")).encode()
        start_response(status, [("Content-Type", "application/json"),
                                ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
        return [body]
