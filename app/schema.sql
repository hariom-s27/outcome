-- Applied at start-up by api and worker under an advisory lock (app/db.py). Idempotent.

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

CREATE INDEX IF NOT EXISTS jobs_pending_idx ON jobs (created_at) WHERE status = 'PENDING';

-- P1-05: uploaded bytes live here until the job is terminal, then the row is deleted.
CREATE TABLE IF NOT EXISTS job_files (
    job_id  uuid PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    content bytea NOT NULL
);

-- P1-07 (extended in Part C): one row per state change, metadata only.
CREATE TABLE IF NOT EXISTS job_events (
    id     bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    at     timestamptz NOT NULL DEFAULT now(),
    event  text NOT NULL
);

CREATE INDEX IF NOT EXISTS job_events_job_idx ON job_events (job_id);
