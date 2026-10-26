"""Signed local identity, canonical quotes, and atomic mock purchases.

SQLite uses the Python standard library. PostgreSQL uses optional psycopg 3.
Both backends are local demos; no payment processor or real money is involved.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable, Iterator
from uuid import uuid4

from .audit import append_event, new_event, record_event

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "agent-commerce-security-demo"
AUDIENCE = "agent-commerce-security-api"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class SecurityError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _encode(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(segment: str) -> dict:
    if not segment or not TOKEN_PATTERN.fullmatch(segment):
        raise ValueError("invalid token encoding")
    raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != segment:
        raise ValueError("noncanonical token encoding")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("token JSON must be an object")
    return value


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    tenant_id: str
    scopes: frozenset[str]


class TokenAuthority:
    def __init__(self, secret: bytes, clock: Callable[[], datetime] | None = None):
        if len(secret) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        self._secret = secret
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(self, user_id: str, tenant_id: str, scopes: list[str], ttl_seconds: int = 900) -> str:
        if not user_id or not tenant_id or not scopes or ttl_seconds < 1 or ttl_seconds > 3600:
            raise ValueError("invalid token request")
        now = int(self._clock().timestamp())
        header = _encode({"alg": "HS256", "typ": "JWT"})
        payload = _encode({"iss": ISSUER, "aud": AUDIENCE, "sub": user_id,
                           "tenant_id": tenant_id, "scopes": scopes,
                           "iat": now, "nbf": now, "exp": now + ttl_seconds, "jti": uuid4().hex})
        signing_input = f"{header}.{payload}"
        signature = base64.urlsafe_b64encode(
            hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        return f"{signing_input}.{signature}"

    def verify(self, token: str | None) -> TokenClaims:
        try:
            if type(token) is not str or len(token) > 4096:
                raise ValueError("missing or oversized token")
            header_part, payload_part, signature_part = token.split(".")
            header = _decode(header_part)
            claims = _decode(payload_part)
            if header != {"alg": "HS256", "typ": "JWT"}:
                raise ValueError("unsupported token header")
            if not TOKEN_PATTERN.fullmatch(signature_part):
                raise ValueError("invalid signature encoding")
            expected = hmac.new(self._secret, f"{header_part}.{payload_part}".encode("ascii"), hashlib.sha256).digest()
            provided = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
            if not hmac.compare_digest(expected, provided):
                raise ValueError("bad token signature")
            now = int(self._clock().timestamp())
            if claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE:
                raise ValueError("wrong issuer or audience")
            if any(type(claims.get(key)) is not int for key in ("iat", "nbf", "exp")):
                raise ValueError("invalid token time")
            if not (claims["iat"] <= now and claims["nbf"] <= now < claims["exp"] <= claims["iat"] + 3600):
                raise ValueError("expired or future token")
            user_id, tenant_id, scopes = claims.get("sub"), claims.get("tenant_id"), claims.get("scopes")
            if (type(user_id) is not str or not user_id or type(tenant_id) is not str or not tenant_id
                    or not isinstance(scopes, list) or not scopes or any(type(s) is not str or not s for s in scopes)
                    or len(scopes) != len(set(scopes))):
                raise ValueError("invalid token identity or scopes")
            return TokenClaims(user_id, tenant_id, frozenset(scopes))
        except (ValueError, UnicodeError, TypeError, base64.binascii.Error) as error:
            raise SecurityError("TOKEN_INVALID") from error


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    scopes: frozenset[str]


class Store:
    is_postgres = False
    schema_path = ROOT / "migrations" / "001_sqlite.sql"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self, seed: dict) -> None:
        with self.connect() as connection:
            connection.executescript(self.schema_path.read_text(encoding="utf-8"))
            connection.execute("BEGIN IMMEDIATE")
            try:
                for tenant in seed["tenants"]:
                    connection.execute("INSERT OR IGNORE INTO tenants VALUES (?, ?)",
                                       (tenant["tenant_id"], tenant["display_name"]))
                for user in seed["users"]:
                    connection.execute("INSERT OR IGNORE INTO demo_users VALUES (?, ?, ?, ?)",
                                       (user["user_id"], user["tenant_id"], int(user["active"]), json.dumps(user["scopes"])))
                for seller in seed["sellers"]:
                    connection.execute("INSERT OR IGNORE INTO sellers VALUES (?, ?)",
                                       (seller["seller_id"], int(seller["approved"])))
                for service in seed["services"]:
                    connection.execute("INSERT OR IGNORE INTO services (service_id, seller_id, price_minor, currency, active, report_id) VALUES (?, ?, ?, ?, ?, ?)",
                                       (service["service_id"], service["seller_id"], service["price_minor"],
                                        service["currency"], int(service["active"]), service["report_id"]))
                for report in seed["paid_reports"]:
                    connection.execute("INSERT OR IGNORE INTO paid_reports VALUES (?, ?, ?, ?)",
                                       (report["report_id"], report["service_id"], report["source_id"], json.dumps(report)))
                for budget in seed["budgets"]:
                    connection.execute("INSERT OR IGNORE INTO budgets (budget_id, tenant_id, user_id, currency, limit_minor, remaining_minor) VALUES (?, ?, ?, ?, ?, ?)",
                                       (budget["budget_id"], budget["tenant_id"], budget["user_id"],
                                        budget["currency"], budget["limit_minor"], budget["remaining_minor"]))
                connection.commit()
            except Exception:
                connection.rollback()
                raise


class _PostgresConnection:
    """Small query adapter around psycopg's normal parameterized connection."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params: tuple = ()):
        if sql == "BEGIN IMMEDIATE":
            sql = "BEGIN"
        elif sql.startswith("INSERT OR IGNORE INTO "):
            sql = sql.replace("INSERT OR IGNORE INTO ", "INSERT INTO ", 1) + " ON CONFLICT DO NOTHING"
        return self.raw.execute(sql.replace("?", "%s"), params)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.raw.execute(statement)

    def commit(self) -> None:
        self.raw.execute("COMMIT")

    def rollback(self) -> None:
        self.raw.execute("ROLLBACK")


class PostgresStore(Store):
    """PostgreSQL backend; install psycopg 3 and use a dedicated demo database."""

    is_postgres = True
    schema_path = ROOT / "migrations" / "001_postgres.sql"

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("PostgreSQL requires psycopg 3; install psycopg[binary]") from error
        raw = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
        try:
            yield _PostgresConnection(raw)
        finally:
            raw.close()


class CommerceService:
    def __init__(self, store: Store | PostgresStore, authority: TokenAuthority, policy: dict,
                 clock: Callable[[], datetime] | None = None):
        self.store = store
        self.authority = authority
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def audit_decision(self, role: str, action: str, decision: str, reason_code: str, **context) -> None:
        record_event(self.store, new_event(role, action, decision, reason_code, **context))

    def principal(self, token: str | None, required_scope: str | None = None,
                  expected_tenant: str | None = None, expected_user: str | None = None) -> Principal:
        claims = self.authority.verify(token)
        with self.store.connect() as connection:
            user = connection.execute("SELECT * FROM demo_users WHERE user_id = ?", (claims.user_id,)).fetchone()
        if user is None or not user["active"]:
            raise SecurityError("USER_INACTIVE")
        if claims.tenant_id != user["tenant_id"] or (expected_tenant is not None and expected_tenant != user["tenant_id"]):
            raise SecurityError("TENANT_DENIED")
        if expected_user is not None and expected_user != claims.user_id:
            raise SecurityError("USER_DENIED")
        scopes = claims.scopes & frozenset(json.loads(user["scopes_json"]))
        if required_scope is not None and required_scope not in scopes:
            raise SecurityError("USER_SCOPE_DENIED")
        return Principal(claims.user_id, user["tenant_id"], scopes)

    def quote(self, token: str, service_id: str, *, agent_role: str = "buyer",
              run_id: str | None = None, trace_id: str | None = None,
              span_id: str | None = None, parent_span_id: str | None = None) -> dict:
        try:
            return self._quote(token, service_id, agent_role=agent_role, run_id=run_id,
                               trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id)
        except SecurityError as error:
            self.audit_decision(agent_role, "get_quote", "deny", error.code,
                                run_id=run_id, trace_id=trace_id, parent_span_id=parent_span_id)
            raise

    def _quote(self, token: str, service_id: str, *, agent_role: str,
               run_id: str | None, trace_id: str | None,
               span_id: str | None, parent_span_id: str | None) -> dict:
        if agent_role != "buyer":
            raise SecurityError("ROLE_TOOL_DENIED")
        principal = self.principal(token, "quote:read")
        if type(service_id) is not str or not service_id:
            raise SecurityError("RESOURCE_DENIED")
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                service = connection.execute("SELECT * FROM services WHERE service_id = ?", (service_id,)).fetchone()
                if service is None or not service["active"]:
                    raise SecurityError("SERVICE_UNAVAILABLE")
                quote = {"quote_id": uuid4().hex, "tenant_id": principal.tenant_id,
                         "user_id": principal.user_id, "service_id": service_id,
                         "amount_minor": service["price_minor"], "currency": service["currency"],
                         "service_version": service["version"],
                         "expires_at": int(self.clock().timestamp()) + self.policy["quote_ttl_seconds"]}
                connection.execute("INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(quote.values()))
                append_event(connection, new_event(agent_role, "get_quote", "allow", "OK", run_id=run_id,
                                                   trace_id=trace_id, tenant_id=principal.tenant_id,
                                                   user_id=principal.user_id, span_id=span_id,
                                                   parent_span_id=parent_span_id))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {key: quote[key] for key in ("quote_id", "service_id", "amount_minor", "currency", "expires_at")}

    def purchase(self, token: str, quote_id: str, request_id: str, *, agent_role: str = "buyer",
                 run_id: str | None = None, trace_id: str | None = None,
                 span_id: str | None = None, parent_span_id: str | None = None) -> dict:
        try:
            return self._purchase(token, quote_id, request_id, agent_role=agent_role,
                                  run_id=run_id, trace_id=trace_id,
                                  span_id=span_id, parent_span_id=parent_span_id)
        except SecurityError as error:
            self.audit_decision(agent_role, "purchase_service", "deny", error.code,
                                run_id=run_id, trace_id=trace_id, parent_span_id=parent_span_id)
            raise

    def _purchase(self, token: str, quote_id: str, request_id: str, *, agent_role: str,
                  run_id: str | None, trace_id: str | None,
                  span_id: str | None, parent_span_id: str | None) -> dict:
        if agent_role != "buyer":
            raise SecurityError("ROLE_TOOL_DENIED")
        principal = self.principal(token, "purchase:write")
        if (type(quote_id) is not str or not quote_id or type(request_id) is not str
                or not 1 <= len(request_id) <= 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", request_id)):
            raise SecurityError("PURCHASE_SCHEMA_DENIED")
        fingerprint = hashlib.sha256(json.dumps({"quote_id": quote_id, "tenant_id": principal.tenant_id,
                                                  "user_id": principal.user_id}, sort_keys=True).encode()).hexdigest()
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if self.store.is_postgres:
                    connection.execute("SELECT pg_advisory_xact_lock(hashtext(?))",
                                       (principal.tenant_id + ":" + request_id,))
                existing = connection.execute("SELECT * FROM purchases WHERE tenant_id = ? AND request_id = ?",
                                              (principal.tenant_id, request_id)).fetchone()
                if existing is not None:
                    if existing["request_fingerprint"] != fingerprint:
                        raise SecurityError("IDEMPOTENCY_CONFLICT")
                    receipt = json.loads(existing["receipt_json"])
                    append_event(connection, new_event(agent_role, "purchase_service", "allow", "IDEMPOTENT_REPLAY",
                                                       run_id=run_id, trace_id=trace_id,
                                                       tenant_id=principal.tenant_id, user_id=principal.user_id,
                                                       span_id=span_id, parent_span_id=parent_span_id))
                    connection.commit()
                    return {**receipt, "idempotent_replay": True}
                quote_query = "SELECT * FROM quotes WHERE quote_id = ?"
                if self.store.is_postgres:
                    quote_query += " FOR UPDATE"
                quote = connection.execute(quote_query, (quote_id,)).fetchone()
                if quote is None:
                    raise SecurityError("QUOTE_NOT_FOUND")
                if quote["tenant_id"] != principal.tenant_id or quote["user_id"] != principal.user_id:
                    raise SecurityError("QUOTE_OWNER_DENIED")
                if connection.execute("SELECT 1 FROM purchases WHERE quote_id = ?", (quote_id,)).fetchone():
                    raise SecurityError("QUOTE_ALREADY_USED")
                if quote["expires_at"] <= int(self.clock().timestamp()):
                    raise SecurityError("QUOTE_EXPIRED")
                service = connection.execute("SELECT * FROM services WHERE service_id = ?", (quote["service_id"],)).fetchone()
                if (service is None or not service["active"] or quote["service_version"] != service["version"]
                        or quote["amount_minor"] != service["price_minor"] or quote["currency"] != service["currency"]):
                    raise SecurityError("QUOTE_CHANGED")
                seller = connection.execute("SELECT * FROM sellers WHERE seller_id = ?", (service["seller_id"],)).fetchone()
                if seller is None or not seller["approved"] or service["seller_id"] not in self.policy["approved_seller_ids"]:
                    raise SecurityError("SELLER_BLOCKED")
                if quote["amount_minor"] > self.policy["max_single_purchase_minor"]:
                    raise SecurityError("RISK_LIMIT")
                updated = connection.execute("UPDATE budgets SET remaining_minor = remaining_minor - ?, version = version + 1 "
                                             "WHERE tenant_id = ? AND user_id = ? AND currency = ? AND remaining_minor >= ?",
                                             (quote["amount_minor"], principal.tenant_id, principal.user_id,
                                              quote["currency"], quote["amount_minor"]))
                if updated.rowcount != 1:
                    raise SecurityError("BUDGET_EXCEEDED")
                remaining = connection.execute("SELECT remaining_minor FROM budgets WHERE user_id = ? AND currency = ?",
                                               (principal.user_id, quote["currency"])).fetchone()["remaining_minor"]
                report = connection.execute("SELECT * FROM paid_reports WHERE report_id = ? AND service_id = ?",
                                            (service["report_id"], service["service_id"])).fetchone()
                if report is None:
                    raise SecurityError("REPORT_MISSING")
                purchase_id = uuid4().hex
                receipt = {"purchase_id": purchase_id, "quote_id": quote_id,
                           "amount_minor": quote["amount_minor"], "currency": quote["currency"],
                           "remaining_minor": remaining, "report_id": report["report_id"],
                           "source_id": report["source_id"], "report": json.loads(report["report_json"]),
                           "idempotent_replay": False}
                connection.execute("INSERT INTO purchases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (purchase_id, principal.tenant_id, principal.user_id, quote_id, request_id,
                                    fingerprint, quote["amount_minor"], quote["currency"], json.dumps(receipt)))
                connection.execute("INSERT INTO mock_ledger VALUES (?, ?, ?, ?, ?, ?)",
                                   (uuid4().hex, purchase_id, principal.tenant_id, principal.user_id,
                                    -quote["amount_minor"], quote["currency"]))
                append_event(connection, new_event(agent_role, "purchase_service", "allow", "OK",
                                                   run_id=run_id, trace_id=trace_id,
                                                   tenant_id=principal.tenant_id, user_id=principal.user_id,
                                                   span_id=span_id, parent_span_id=parent_span_id))
                connection.commit()
                return receipt
            except Exception:
                connection.rollback()
                raise
