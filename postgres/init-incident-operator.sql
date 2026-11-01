-- Init script for incident-operator's database (prod postgres): incidents, collected evidence, model turns.
-- Run as the postgres superuser inside postgres-0; the password comes from a psql variable so it is never committed.
-- The service creates its own tables on start. infra/incident-operator/scripts/create-secrets.sh runs this (it
-- generates the password, runs the script, and stores the URL in Secret incident-operator-db).

CREATE ROLE incident_operator WITH LOGIN PASSWORD :'pw';

CREATE DATABASE incident_operator OWNER incident_operator;

\c incident_operator
GRANT ALL ON SCHEMA public TO incident_operator;
