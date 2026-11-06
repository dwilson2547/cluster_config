-- Init script for slashdot-news-archive's database (web-scrapers/slashdot-news-archive), on the
-- pgvector postgres (postgres-pgvector-0): semantic search over stories needs the `vector`
-- extension, which only a superuser can create, so it is created here. The scraper creates
-- its own tables (schema in scraper.py, applied at start-up).
-- Run as the superuser; the password comes from a psql variable so it is never committed:
--   PW=$(openssl rand -hex 24)
--   kubectl -n postgres exec -i postgres-pgvector-0 -- sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v pw="$1"' _ "$PW" < init-slashdot-news.sql
--   kubectl -n slashdot-news create secret generic slashdot-news-db --from-literal=DATABASE_URL=...
-- DATABASE_URL is the usual postgresql URL: user slashdot_news, password $PW, host
-- postgres-pgvector.postgres.svc.cluster.local, port 5432, database slashdot_news.

CREATE ROLE slashdot_news WITH LOGIN PASSWORD :'pw';

CREATE DATABASE slashdot_news OWNER slashdot_news;
REVOKE CONNECT ON DATABASE slashdot_news FROM PUBLIC;

\c slashdot_news
GRANT ALL ON SCHEMA public TO slashdot_news;
CREATE EXTENSION IF NOT EXISTS vector;
