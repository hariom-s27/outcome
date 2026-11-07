-- Applied at start-up by api and worker under an advisory lock (app/db.py). Idempotent:
-- safe on an empty DB and on a DB created by an earlier version of this file.

CREATE TABLE IF NOT EXISTS jobs (
    id          uuid PRIMARY KEY,
    org_id      text,
    status      text NOT NULL
                CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')),
    stage       text,
    field_list  jsonb NOT NULL,
    file_type   text NOT NULL CHECK (file_type IN ('pdf', 'docx', 'xlsx', 'csv')),
    file_size   bigint NOT NULL,
    webhook_url text,
    result      jsonb,
    error       jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- P1-06 claim/lease/fence, P1-08 deadline, poison-job attempt count (Part C)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS fence       bigint NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts    integer NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_owner text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline_at timestamptz;
UPDATE jobs SET deadline_at = created_at + interval '1500 seconds' WHERE deadline_at IS NULL;
ALTER TABLE jobs ALTER COLUMN deadline_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS jobs_pending_idx ON jobs (created_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS jobs_lease_idx ON jobs (lease_until) WHERE status = 'RUNNING';
CREATE INDEX IF NOT EXISTS jobs_deadline_idx ON jobs (deadline_at)
    WHERE status IN ('PENDING', 'RUNNING');

-- P1-07: a terminal row never changes again, whoever writes it.
CREATE OR REPLACE FUNCTION jobs_terminal_once() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('SUCCESS', 'PARTIAL', 'FAILED') THEN
        RAISE EXCEPTION 'job % is terminal (%); it cannot change', OLD.id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER jobs_terminal_once
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION jobs_terminal_once();

-- P1-05: uploaded bytes live here until the job is terminal, then the row is deleted.
CREATE TABLE IF NOT EXISTS job_files (
    job_id  uuid PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    content bytea NOT NULL
);

-- P1-07: one row per state change, metadata only.
CREATE TABLE IF NOT EXISTS job_events (
    id     bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    at     timestamptz NOT NULL DEFAULT now(),
    event  text NOT NULL
);
ALTER TABLE job_events ADD COLUMN IF NOT EXISTS fence  bigint;
ALTER TABLE job_events ADD COLUMN IF NOT EXISTS worker text;
ALTER TABLE job_events ADD COLUMN IF NOT EXISTS reason text;

CREATE INDEX IF NOT EXISTS job_events_job_idx ON job_events (job_id);
-- at most one terminal event per job, enforced by the DB
CREATE UNIQUE INDEX IF NOT EXISTS job_events_one_terminal
    ON job_events (job_id) WHERE event IN ('SUCCESS', 'PARTIAL', 'FAILED');

-- P2-09 / R21: LLM cost ledger, one row per attempt (and per dev-cache hit). Metadata only:
-- never prompt or response text. No FK to jobs: dev scripts may call without a job row.
CREATE TABLE IF NOT EXISTS llm_calls (
    id               bigserial PRIMARY KEY,
    at               timestamptz NOT NULL DEFAULT now(),
    job_id           uuid,
    purpose          text,
    attempt          integer NOT NULL,
    model_requested  text NOT NULL,
    model_returned   text,
    model_mismatch   boolean NOT NULL DEFAULT false,
    status           text NOT NULL,
    http_status      integer,
    finish_reason    text,
    tokens_in        integer NOT NULL DEFAULT 0,
    tokens_out       integer NOT NULL DEFAULT 0,
    tokens_reasoning integer,
    tokens_cached    integer,
    cost_reported    double precision,
    cost_computed    double precision NOT NULL DEFAULT 0,
    latency_ms       integer NOT NULL DEFAULT 0,
    cache_hit        boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS llm_calls_job_idx ON llm_calls (job_id);

-- P2-07: global in-flight cap. A slot is free when its lease has run out, so a crashed
-- holder's slot frees itself. Rows 0..cap-1 are inserted by the client at start-up.
CREATE TABLE IF NOT EXISTS llm_slots (
    slot        integer PRIMARY KEY,
    holder      text,
    lease_until timestamptz
);

-- P2-07 shared 429 cool-down; P2-29 circuit breaker. Exactly one row.
CREATE TABLE IF NOT EXISTS llm_state (
    id                   integer PRIMARY KEY CHECK (id = 1),
    cooldown_until       timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    breaker_open_until   timestamptz
);
INSERT INTO llm_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- P2-31 / P2-33 additions (idempotent for databases created before them)
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS reasoning_effort text;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS reasoning_param_dropped boolean NOT NULL DEFAULT false;
-- half-open breaker: when the pause ends exactly one caller holds the probe (lease, so a
-- crashed prober frees it). The claim names the breaker_open_until value it waited out.
ALTER TABLE llm_state ADD COLUMN IF NOT EXISTS probe_until timestamptz;
-- P2-36: the high-side input estimate made before the call, next to the real prompt tokens
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS tokens_estimated integer;
-- dev-cache hit rows: what the call that filled the cache cost (graders have no cache)
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS cost_original double precision;
