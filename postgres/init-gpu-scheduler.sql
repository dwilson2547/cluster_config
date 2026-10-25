-- Init script for gpu-scheduler's job-queue database (prod postgres).
-- Run as the postgres superuser inside postgres-0; the password comes from a psql variable so it is
-- never committed. The service creates its own tables on start.
-- Example (generates the password, runs this, and stores the URL in the service's Secret):
--   PW=$(openssl rand -hex 24)
--   kubectl -n postgres exec -i postgres-0 -- sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v pw="$1"' _ "$PW" < init-gpu-scheduler.sql
--   then create Secret gpu-scheduler-db in namespace gpu-scheduler with key DATABASE_URL: the postgresql URL for
--   user gpu_scheduler (that password) at postgres.postgres.svc.cluster.local:5432, database gpu_scheduler.

CREATE ROLE gpu_scheduler WITH LOGIN PASSWORD :'pw';

CREATE DATABASE gpu_scheduler OWNER gpu_scheduler;

\c gpu_scheduler
GRANT ALL ON SCHEMA public TO gpu_scheduler;
