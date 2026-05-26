-- Init script for photo-dump dev database and user.
-- Run as the postgres superuser against postgres-dev.
-- Example:
--   psql -v photo_dump_dev_password='change-me' -f init-photo-dump-dev.sql

CREATE ROLE photo_dump_dev WITH LOGIN PASSWORD :'photo_dump_dev_password';

CREATE DATABASE photo_dump OWNER photo_dump_dev;

\c photo_dump
GRANT ALL ON SCHEMA public TO photo_dump_dev;
