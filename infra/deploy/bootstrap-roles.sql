-- One-time setup of the managed PostgreSQL 16 database (#112, Database Design 9.1).
-- Run by the provider's administrator (a superuser, or a role with CREATEROLE and
-- BYPASSRLS), before the first deploy. Re-running it is safe, and is how a role's
-- password is rotated (docs/runbooks/deploy.md). Passwords arrive as psql variables,
-- never in this file or the shell history:
--
--   psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
--     -v owner_password="$OWNER_PW" -v api_password="$API_PW" \
--     -v worker_password="$WORKER_PW" -v readonly_password="$READONLY_PW" \
--     -f bootstrap-roles.sql
--
-- listenup_owner runs migrations and the backup service, and owns every schema. The
-- baseline migration creates the other three roles when missing and sets their
-- timeouts; creating them here first lets them log in, and gives listenup_worker the
-- BYPASSRLS attribute that only an administrator can grant. listenup_owner gets admin
-- rights over them (not their privileges) so its migrations can set their timeouts.
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE listenup_owner LOGIN CREATEROLE CREATEDB PASSWORD %L', :'owner_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_owner') \gexec
SELECT format('ALTER ROLE listenup_owner LOGIN CREATEROLE CREATEDB PASSWORD %L', :'owner_password') \gexec

SELECT format('CREATE ROLE listenup_api LOGIN PASSWORD %L', :'api_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_api') \gexec
SELECT format('ALTER ROLE listenup_api LOGIN NOBYPASSRLS PASSWORD %L', :'api_password') \gexec

SELECT format('CREATE ROLE listenup_worker LOGIN BYPASSRLS PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_worker') \gexec
SELECT format('ALTER ROLE listenup_worker LOGIN BYPASSRLS PASSWORD %L', :'worker_password') \gexec

SELECT format('CREATE ROLE listenup_readonly LOGIN PASSWORD %L', :'readonly_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_readonly') \gexec
SELECT format('ALTER ROLE listenup_readonly LOGIN NOBYPASSRLS PASSWORD %L', :'readonly_password') \gexec

GRANT listenup_api, listenup_worker, listenup_readonly TO listenup_owner
  WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;

SELECT 'CREATE DATABASE listenup OWNER listenup_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'listenup') \gexec

-- Only the four roles may connect.
REVOKE CONNECT, TEMPORARY ON DATABASE listenup FROM PUBLIC;
GRANT CONNECT ON DATABASE listenup TO listenup_api, listenup_worker, listenup_readonly;

-- Report what the services will log in as.
SELECT rolname, rolcanlogin AS login, rolbypassrls AS bypassrls, rolcreaterole AS createrole,
       rolsuper AS superuser
FROM pg_roles WHERE rolname LIKE 'listenup\_%' ORDER BY rolname;
