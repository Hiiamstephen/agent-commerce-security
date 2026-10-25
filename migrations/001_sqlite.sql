PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_users (
    user_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    scopes_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sellers (
    seller_id TEXT PRIMARY KEY,
    approved INTEGER NOT NULL CHECK (approved IN (0, 1))
);
CREATE TABLE IF NOT EXISTS services (
    service_id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    price_minor INTEGER NOT NULL CHECK (price_minor > 0),
    currency TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    report_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paid_reports (
    report_id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL UNIQUE REFERENCES services(service_id),
    source_id TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    budget_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id TEXT NOT NULL REFERENCES demo_users(user_id),
    currency TEXT NOT NULL,
    limit_minor INTEGER NOT NULL CHECK (limit_minor >= 0),
    remaining_minor INTEGER NOT NULL CHECK (remaining_minor >= 0 AND remaining_minor <= limit_minor),
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (user_id, currency)
);
CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id TEXT NOT NULL REFERENCES demo_users(user_id),
    service_id TEXT NOT NULL REFERENCES services(service_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL,
    service_version INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
    purchase_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id TEXT NOT NULL REFERENCES demo_users(user_id),
    quote_id TEXT NOT NULL REFERENCES quotes(quote_id),
    request_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    UNIQUE (tenant_id, request_id),
    UNIQUE (quote_id)
);
CREATE TABLE IF NOT EXISTS mock_ledger (
    entry_id TEXT PRIMARY KEY,
    purchase_id TEXT NOT NULL UNIQUE REFERENCES purchases(purchase_id),
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id TEXT NOT NULL REFERENCES demo_users(user_id),
    delta_minor INTEGER NOT NULL CHECK (delta_minor < 0),
    currency TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    tenant_id TEXT,
    user_id TEXT,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
    reason_code TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    event_id TEXT PRIMARY KEY REFERENCES audit_events(event_id),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS security_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
