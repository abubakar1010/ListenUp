-- One-time setup of the managed PostgreSQL 16 database (#112, Database Design 9.1).
-- Run by the provider's administrator (a superuser, or a role with CREATEROLE,
-- CREATEDB and BYPASSRLS, as on managed services), before the first deploy. Re-running
-- it is safe, and is how a role's password is rotated (docs/runbooks/deploy.md).
--
-- It takes SCRAM verifiers, never passwords: a statement that carries a password is
-- written to the server log when it fails, and on every run where the provider logs
-- DDL. Make each verifier from the password on standard input, so neither appears in
-- the shell history or the process list:
--
--   API_VERIFIER="$(printf '%s' "$API_PW" | python -m listenup.ops.scram_verifier)"
--   psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
--     -v owner_verifier="$OWNER_VERIFIER" -v api_verifier="$API_VERIFIER" \
--     -v worker_verifier="$WORKER_VERIFIER" -v readonly_verifier="$READONLY_VERIFIER" \
--     -f bootstrap-roles.sql
--
-- `keep` in place of a verifier leaves an existing role's password as it is, so one
-- role can be rotated without the others.
--
-- listenup_owner runs migrations and the backup service, and owns every schema. The
-- baseline migration creates the other three roles when missing and sets their
-- timeouts; creating them here first lets them log in, and gives listenup_worker the
-- BYPASSRLS attribute that only an administrator can grant. listenup_owner gets admin
-- rights over them (not their privileges) so its migrations can set their timeouts.
\set ON_ERROR_STOP on

-- Refuse a plain password before any statement that could be logged carries it.
SELECT format(
  'DO $$BEGIN RAISE EXCEPTION %L; END$$',
  name || ' must be a SCRAM-SHA-256 verifier (python -m listenup.ops.scram_verifier) or keep'
)
FROM (VALUES ('owner_verifier', :'owner_verifier'), ('api_verifier', :'api_verifier'),
             ('worker_verifier', :'worker_verifier'),
             ('readonly_verifier', :'readonly_verifier')) AS given (name, value)
WHERE value <> 'keep'
  AND value !~ '^SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$' \gexec

SELECT format('CREATE ROLE listenup_owner LOGIN CREATEROLE CREATEDB PASSWORD %L', :'owner_verifier')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_owner') \gexec
SELECT format('ALTER ROLE listenup_owner LOGIN CREATEROLE CREATEDB PASSWORD %L', :'owner_verifier')
WHERE :'owner_verifier' <> 'keep' \gexec
ALTER ROLE listenup_owner LOGIN CREATEROLE CREATEDB;

SELECT format('CREATE ROLE listenup_api LOGIN PASSWORD %L', :'api_verifier')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_api') \gexec
SELECT format('ALTER ROLE listenup_api PASSWORD %L', :'api_verifier')
WHERE :'api_verifier' <> 'keep' \gexec
ALTER ROLE listenup_api LOGIN NOBYPASSRLS;

SELECT format('CREATE ROLE listenup_worker LOGIN BYPASSRLS PASSWORD %L', :'worker_verifier')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_worker') \gexec
SELECT format('ALTER ROLE listenup_worker PASSWORD %L', :'worker_verifier')
WHERE :'worker_verifier' <> 'keep' \gexec
ALTER ROLE listenup_worker LOGIN BYPASSRLS;

SELECT format('CREATE ROLE listenup_readonly LOGIN PASSWORD %L', :'readonly_verifier')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_readonly') \gexec
SELECT format('ALTER ROLE listenup_readonly PASSWORD %L', :'readonly_verifier')
WHERE :'readonly_verifier' <> 'keep' \gexec
ALTER ROLE listenup_readonly LOGIN NOBYPASSRLS;

GRANT listenup_api, listenup_worker, listenup_readonly TO listenup_owner
  WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;

-- PostgreSQL 16 gives a non-superuser creator ADMIN on the roles it creates but not
-- SET, and CREATE DATABASE ... OWNER needs SET. The administrator gains no privilege
-- it did not already have through ADMIN.
GRANT listenup_owner TO CURRENT_USER WITH SET TRUE, INHERIT FALSE;

SELECT 'CREATE DATABASE listenup OWNER listenup_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'listenup') \gexec

-- Only the four roles may connect. Run as the owner: a non-superuser administrator
-- holds no grant option on the database, and its REVOKE would only warn.
SET ROLE listenup_owner;
REVOKE CONNECT, TEMPORARY ON DATABASE listenup FROM PUBLIC;
GRANT CONNECT ON DATABASE listenup TO listenup_api, listenup_worker, listenup_readonly;
RESET ROLE;

SELECT 'DO $$BEGIN RAISE EXCEPTION ''PUBLIC can still connect to listenup or create temporary tables''; END$$'
FROM pg_database AS d, aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) AS acl
WHERE d.datname = 'listenup' AND acl.grantee = 0
  AND acl.privilege_type IN ('CONNECT', 'TEMPORARY')
LIMIT 1 \gexec

-- Report what the services will log in as.
SELECT rolname, rolcanlogin AS login, rolbypassrls AS bypassrls, rolcreaterole AS createrole,
       rolsuper AS superuser
FROM pg_roles WHERE rolname LIKE 'listenup\_%' ORDER BY rolname;
