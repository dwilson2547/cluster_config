-- Init script for webdoc's database, on the pgvector postgres (postgres-pgvector-0): webdoc's
-- semantic search (design §8, phase 3) needs the `vector` extension, which only a superuser can
-- create, so it is created here. The app creates its own tables (Alembic, at start-up).
-- Run as the superuser; the password comes from a psql variable so it is never committed:
--   PW=$(openssl rand -hex 24)
--   kubectl -n postgres exec -i postgres-pgvector-0 -- sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v pw="$1"' _ "$PW" < init-webdoc.sql
--   kubectl -n webdoc create secret generic webdoc-db \
--     --from-literal=DATABASE_URL="postgresql://webdoc:$PW@postgres-pgvector.postgres.svc.cluster.local:5432/webdoc"

CREATE ROLE webdoc WITH LOGIN PASSWORD :'pw';

CREATE DATABASE webdoc OWNER webdoc;
REVOKE CONNECT ON DATABASE webdoc FROM PUBLIC;

\c webdoc
GRANT ALL ON SCHEMA public TO webdoc;
CREATE EXTENSION IF NOT EXISTS vector;
