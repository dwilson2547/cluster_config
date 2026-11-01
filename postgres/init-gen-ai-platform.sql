-- Init script for gen-ai-platform's database (prod postgres): users, sessions, projects, artifacts (images live in
-- AIStor). Run as the postgres superuser inside postgres-0; the password comes from a psql variable so it is never
-- committed. The app creates its own tables on start. ai/gen-ai-platform/scripts/create-secrets.sh runs this (it
-- generates the password, runs the script, and stores the URL in Secret gen-ai-platform-db).

CREATE ROLE gen_ai_platform WITH LOGIN PASSWORD :'pw';

CREATE DATABASE gen_ai_platform OWNER gen_ai_platform;

\c gen_ai_platform
GRANT ALL ON SCHEMA public TO gen_ai_platform;
