CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subsidiary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    current_phase TEXT NOT NULL DEFAULT 'phase0',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_batches (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '',
    source_team TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT '',
    authority_level TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidentiality TEXT NOT NULL DEFAULT 'INTERNAL',
    status TEXT NOT NULL DEFAULT 'REGISTERED',
    manifest_path TEXT NOT NULL DEFAULT '',
    batch_dir TEXT NOT NULL,
    integrity_hash TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL,
    UNIQUE (batch_dir)
);

CREATE TABLE IF NOT EXISTS source_artifacts (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES source_batches(id),
    relative_path TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'unknown',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    parser_status TEXT NOT NULL DEFAULT 'PENDING',
    duplicate_of TEXT,
    registered_at TEXT NOT NULL,
    UNIQUE (batch_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON source_artifacts(sha256);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    artifact_id TEXT REFERENCES source_artifacts(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'CONFIRMED',
    registered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_assessment ON evidence(assessment_id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    closed_at TEXT,
    summary_path TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS node_states (
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    cycles INTEGER NOT NULL DEFAULT 0,
    last_execution_id TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (assessment_id, node_id)
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    node_id TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    error TEXT,
    prompt_hash TEXT,
    model TEXT,
    provider TEXT,
    opencode_session_id TEXT,
    result_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_node ON executions(assessment_id, node_id);

CREATE TABLE IF NOT EXISTS human_requests (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    node_id TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    title TEXT NOT NULL,
    missing_info TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    expected_provider TEXT NOT NULL DEFAULT '',
    retrieval_attempted TEXT NOT NULL DEFAULT '',
    accepted_formats TEXT NOT NULL DEFAULT '',
    destination_batch TEXT NOT NULL DEFAULT '',
    security_notes TEXT NOT NULL DEFAULT '',
    resume_node TEXT NOT NULL DEFAULT '',
    query_pack_path TEXT NOT NULL DEFAULT '',
    request_doc_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_batch_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON human_requests(assessment_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_open_unique
    ON human_requests(assessment_id, node_id, missing_info)
    WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    statement TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    source_locators TEXT NOT NULL DEFAULT '[]',
    extraction_method TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    superseded_by TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_assessment ON findings(assessment_id, status);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    node_id TEXT NOT NULL,
    execution_id TEXT,
    inputs TEXT NOT NULL DEFAULT '{}',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    selected_route TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'CONFIRMED',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assumptions (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    statement TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risks (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    statement TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'MEDIUM',
    mitigation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gaps (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    description TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    label TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    db_snapshot_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    assessment_id TEXT,
    session_id TEXT,
    execution_id TEXT,
    node_id TEXT,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    prompt_hash TEXT,
    model TEXT,
    provider TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    result_status TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_assessment ON audit_events(assessment_id, seq);

CREATE TABLE IF NOT EXISTS data_objects (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    object_type TEXT NOT NULL,
    schema_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    first_seen_evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (assessment_id, object_type, normalized_name)
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    relationship TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'DIRECTED',
    extraction_method TEXT NOT NULL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
    validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED',
    depth INTEGER NOT NULL DEFAULT 0,
    limitations TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (assessment_id, source_node, target_node, relationship)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
