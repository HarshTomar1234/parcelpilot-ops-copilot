-- ParcelPilot Ops Copilot - Phase 1 schema, extended in Phase 4 with the
-- `actions` audit trail (prepare/confirm/execute - app/actions/).
-- Mirrors the real workbook schema (docs/data_dictionary.md) and the real
-- source pack (docs/source_inventory.md). No generic EAV tables.

PRAGMA foreign_keys = ON;

-- Free-form key/value facts about this build: snapshot_time, currency,
-- ingested_at, source_pack checksum summary.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE sources (
    source_id        TEXT PRIMARY KEY,
    filename         TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    status           TEXT NOT NULL,
    version          TEXT,
    effective_date   TEXT NOT NULL,
    expiry_date      TEXT,
    supersedes       TEXT,
    superseded_by    TEXT,
    scope_kind       TEXT NOT NULL,
    scope_account_id TEXT,
    authority_class  TEXT NOT NULL,
    checksum         TEXT NOT NULL,
    bytes            INTEGER NOT NULL,
    provenance       TEXT NOT NULL
);

CREATE TABLE document_chunks (
    id              INTEGER PRIMARY KEY,
    chunk_id        TEXT NOT NULL UNIQUE,
    source_id       TEXT NOT NULL REFERENCES sources (source_id),
    page            INTEGER NOT NULL,
    section         TEXT,
    text            TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    -- Denormalized from sources, so metadata filtering never needs a join.
    filename        TEXT NOT NULL,
    status          TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    account_scope   TEXT,
    effective_date  TEXT NOT NULL,
    authority_class TEXT NOT NULL
);

CREATE INDEX idx_document_chunks_source_id ON document_chunks (source_id);
CREATE INDEX idx_document_chunks_status ON document_chunks (status);
CREATE INDEX idx_document_chunks_source_type ON document_chunks (source_type);
CREATE INDEX idx_document_chunks_authority_class ON document_chunks (authority_class);
CREATE INDEX idx_document_chunks_account_scope ON document_chunks (account_scope);

-- External-content FTS5 index over normalized_text, keyed by document_chunks.id.
CREATE VIRTUAL TABLE document_chunks_fts USING fts5 (
    normalized_text,
    content = 'document_chunks',
    content_rowid = 'id',
    tokenize = 'porter unicode61'
);

-- One (plan-or-account, severity) -> target row. See app/documents/sla_table.py.
CREATE TABLE sla_targets (
    id                        INTEGER PRIMARY KEY,
    source_id                 TEXT NOT NULL REFERENCES sources (source_id),
    scope_kind                TEXT NOT NULL,  -- 'plan' | 'account'
    plan                      TEXT,
    account_id                TEXT,
    severity                  TEXT NOT NULL,
    target_text               TEXT NOT NULL,
    target_minutes            INTEGER,
    is_24x7                   INTEGER NOT NULL DEFAULT 0,
    requires_business_calendar INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX idx_sla_targets_identity
    ON sla_targets (source_id, severity, COALESCE(plan, ''), COALESCE(account_id, ''));

CREATE TABLE accounts (
    account_id      TEXT PRIMARY KEY,
    account_name    TEXT NOT NULL,
    plan            TEXT NOT NULL,
    status          TEXT NOT NULL,
    csm             TEXT NOT NULL,
    contract_file   TEXT,
    premium_support INTEGER NOT NULL,
    notes           TEXT NOT NULL
);

CREATE TABLE orders (
    order_id                  TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL REFERENCES accounts (account_id),
    carrier                   TEXT NOT NULL,
    status                    TEXT NOT NULL,
    booked_at                 TEXT NOT NULL,
    pickup_window_start       TEXT NOT NULL,
    pickup_window_end         TEXT NOT NULL,
    pickup_actual_at          TEXT,
    shipment_fee_inr          REAL NOT NULL,
    carrier_fault             INTEGER NOT NULL,
    customer_fault            INTEGER NOT NULL,
    cancellation_requested_at TEXT,
    notes                     TEXT NOT NULL
);

CREATE INDEX idx_orders_account_id ON orders (account_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_carrier ON orders (carrier);

CREATE TABLE tickets (
    ticket_id                TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL REFERENCES accounts (account_id),
    created_at                TEXT NOT NULL,
    status                    TEXT NOT NULL,
    subject                   TEXT NOT NULL,
    description                TEXT NOT NULL,
    channel                    TEXT NOT NULL,
    assigned_to                TEXT NOT NULL,
    last_customer_message_at   TEXT NOT NULL,
    historical_resolution      TEXT
);

CREATE INDEX idx_tickets_account_id ON tickets (account_id);
CREATE INDEX idx_tickets_status ON tickets (status);
CREATE INDEX idx_tickets_created_at ON tickets (created_at);

-- Phase 4: the state-changing action audit trail (app/actions/). Every
-- prepare/confirm/execute call writes or updates exactly one row here -
-- this table IS the audit log, not a separate side channel, so there is
-- never a code path that mutates action state without leaving a record.
CREATE TABLE actions (
    action_id        TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    action_type      TEXT NOT NULL,
    target           TEXT NOT NULL,
    proposed_change  TEXT NOT NULL,  -- JSON
    reason           TEXT NOT NULL,
    evidence         TEXT NOT NULL,  -- JSON list[EvidenceRef]
    risk             TEXT NOT NULL,
    payload_hash     TEXT NOT NULL,
    status           TEXT NOT NULL,
    prepared_at      TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    confirmed_at     TEXT,
    executed_at      TEXT,
    idempotency_key  TEXT NOT NULL,
    failure_reason   TEXT
);

CREATE INDEX idx_actions_status ON actions (status);
CREATE INDEX idx_actions_target ON actions (target);
CREATE INDEX idx_actions_user_id ON actions (user_id);
