"""Content-free AI accounting and monthly call partitions (#64).

Revision IDs are story-specific to avoid the concurrent #45 migration.
"""

from alembic import op

revision = "0064_ai_gateway"
down_revision = "32_google_oidc"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE ai.calls (
 id uuid NOT NULL, created_at timestamptz NOT NULL,
 role text NOT NULL CHECK (role IN ('transcription','alignment','speech_assessment','text_ai')),
 task text NOT NULL, provider text NOT NULL, model text NOT NULL,
 version text, prompt_version text,
 latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
 input_units bigint NOT NULL DEFAULT 0 CHECK (input_units >= 0),
 output_units bigint NOT NULL DEFAULT 0 CHECK (output_units >= 0),
 reasoning_tokens bigint NOT NULL DEFAULT 0 CHECK (reasoning_tokens >= 0),
 cache_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_tokens >= 0),
 audio_seconds double precision NOT NULL DEFAULT 0 CHECK (audio_seconds >= 0 AND audio_seconds
< 'Infinity'::float8),
 fallback_depth integer NOT NULL DEFAULT 0 CHECK (fallback_depth >= 0),
 queue_delay_ms bigint NOT NULL DEFAULT 0 CHECK (queue_delay_ms >= 0),
 projected_cost_usd double precision NOT NULL DEFAULT 0 CHECK (projected_cost_usd >= 0 AND
projected_cost_usd < 'Infinity'::float8),
 usage_estimated boolean NOT NULL DEFAULT true,
 outcome text NOT NULL CHECK (outcome IN
('pending','ok','invalid_output','timeout','error','quota','ineligible','cancelled')),
 PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE ai.quota_usage (
 provider text NOT NULL,
 period text NOT NULL CHECK (period IN ('minute','day','month')),
 period_start timestamptz NOT NULL,
 calls bigint NOT NULL DEFAULT 0 CHECK (calls >= 0),
 units bigint NOT NULL DEFAULT 0 CHECK (units >= 0),
 audio_seconds double precision NOT NULL DEFAULT 0 CHECK (audio_seconds >= 0 AND audio_seconds
< 'Infinity'::float8),
 PRIMARY KEY (provider, period, period_start)
);
GRANT SELECT ON ai.calls, ai.quota_usage TO listenup_api, listenup_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai.calls, ai.quota_usage TO listenup_worker;

-- Narrow owner function: workers can maintain only these partitions, not arbitrary DDL.
CREATE FUNCTION ai.maintain_partitions() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET timezone = 'UTC' AS $$
DECLARE start_at timestamptz; end_at timestamptz; child record;
BEGIN
 PERFORM pg_advisory_xact_lock(640037);
 FOR i IN 0..3 LOOP
  start_at := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' +
make_interval(months => i);
  end_at := start_at + interval '1 month';
  EXECUTE format('CREATE TABLE IF NOT EXISTS ai.%I PARTITION OF ai.calls FOR VALUES FROM (%L)
TO (%L)',
    'calls_' || to_char(start_at AT TIME ZONE 'UTC','YYYY_MM'), start_at, end_at);
 END LOOP;
 FOR child IN SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid
   WHERE i.inhparent='ai.calls'::regclass LOOP
  IF child.relname ~ '^calls_[0-9]{4}_[0-9]{2}$'
    AND to_date(substring(child.relname FROM 7), 'YYYY_MM') + interval '1 month' < now() -
interval '90 days' THEN
   EXECUTE format('DROP TABLE ai.%I', child.relname);
  END IF;
 END LOOP;
 DELETE FROM ai.quota_usage WHERE period_start < now() - interval '90 days';
END $$;
REVOKE ALL ON FUNCTION ai.maintain_partitions() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ai.maintain_partitions() TO listenup_worker;
SELECT ai.maintain_partitions();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION ai.maintain_partitions(); DROP TABLE ai.calls; DROP TABLE ai.quota_usage;"
    )
