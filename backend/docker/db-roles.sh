#!/bin/sh
# Least-privilege database roles. Idempotent; runs automatically on the first
# start of an empty database (docker-entrypoint-initdb.d) and by hand on an
# existing one:
#
#   docker compose exec db sh /db-roles.sh
#
# * APP_DB_USER (calmap_app): owns the backend's tables and runs migrations, but is
#   not a superuser — an SQL injection cannot read server files or run programs.
# * BOT_DB_USER (calmap_bot): owns schema "bot" only and cannot read users,
#   diaries or anything else of the backend.
#
# The bootstrap superuser (POSTGRES_USER) stays for maintenance and backups.
set -eu
: "${APP_DB_PASSWORD:?set APP_DB_PASSWORD in .env}"
: "${BOT_DB_PASSWORD:?set BOT_DB_PASSWORD in .env}"
APP_DB_USER="${APP_DB_USER:-calmap_app}"
BOT_DB_USER="${BOT_DB_USER:-calmap_bot}"
DB="${POSTGRES_DB:-calmap}"

psql -q -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-calmap}" --dbname "$DB" \
  -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" \
  -v bot_user="$BOT_DB_USER" -v bot_password="$BOT_DB_PASSWORD" \
  -v db="$DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', :'bot_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'bot_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'app_user', :'app_password') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'bot_user', :'bot_password') \gexec

-- The backend owns the database and schema public (migrations, pg_trgm).
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db', :'app_user') \gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_user') \gexec
-- Existing tables, sequences and views of schema public move to the backend role.
SELECT format('ALTER TABLE public.%I OWNER TO %I', c.relname, :'app_user')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f') \gexec
SELECT format('ALTER SEQUENCE public.%I OWNER TO %I', c.relname, :'app_user')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype IN ('a', 'i')
WHERE n.nspname = 'public' AND c.relkind = 'S' AND d.objid IS NULL \gexec

-- The bot sees only its own schema.
SELECT format('CREATE SCHEMA IF NOT EXISTS bot AUTHORIZATION %I', :'bot_user') \gexec
SELECT format('ALTER SCHEMA bot OWNER TO %I', :'bot_user') \gexec
SELECT format('ALTER TABLE bot.%I OWNER TO %I', c.relname, :'bot_user')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'bot' AND c.relkind IN ('r', 'p') \gexec
-- Only the owner (the backend role) may use schema public; the bot role may not.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SQL
echo "database roles ready: $APP_DB_USER, $BOT_DB_USER"
