#!/usr/bin/env bash
# Move one app database from a plain postgres instance (v17) to a pgvector instance (v16), keeping
# the owner role and its password (copied as the SCRAM hash; no password is handled in clear).
# First used for photo-dump, 2026-10-25.
#
#   migrate-db-to-pgvector.sh <src-pod> <dst-pod> <db> <role> <namespace> <secret> <url-key> <new-host> <deployment>
#   e.g. migrate-db-to-pgvector.sh postgres-0 postgres-pgvector-0 photo_dump photo_dump \
#          photo-dump postgres-photo-dump-creds dburl postgres-pgvector.postgres.svc.cluster.local photo-dump-api
#
# Steps: copy role -> create db + `vector` extension -> plain-SQL dump/restore (dropping v17-only
# `SET transaction_timeout`, which v16 rejects) -> compare exact row counts per table -> repoint the
# app Secret's host -> restart the app -> rename the source db to <db>_moved_<date> (kept for rollback).
# Refuses to run if <db> already exists on the destination. Runs from a box that can `ssh k8s-main`.
set -euo pipefail
[ $# -eq 9 ] || { sed -n 6,10p "$0"; exit 2; }
SRC=$1 DST=$2 DB=$3 ROLE=$4 NS=$5 SECRET=$6 KEY=$7 NEWHOST=$8 DEPLOY=$9
K="microk8s kubectl"
psql_on() {  # psql_on <pod> <db> [psql args...]  (SQL on stdin)
  local pod=$1 db=$2; shift 2
  ssh k8s-main "$K -n postgres exec -i $pod -- sh -c 'psql -U \"\$POSTGRES_USER\" -d $db -v ON_ERROR_STOP=1 $*'"
}

echo "== preflight"
[ "$(echo "select count(*) from pg_database where datname='$DB'" | psql_on "$DST" postgres -At)" = 0 ] \
  || { echo "$DB already exists on $DST; refusing"; exit 1; }
[ "$(echo "select count(*) from pg_available_extensions where name='vector'" | psql_on "$DST" postgres -At)" = 1 ] \
  || { echo "no vector extension on $DST"; exit 1; }

echo "== role $ROLE ($SRC -> $DST)"
ssh k8s-main "$K -n postgres exec $SRC -- sh -c 'pg_dumpall -U \"\$POSTGRES_USER\" --roles-only'" \
  | grep -E "^(CREATE|ALTER) ROLE $ROLE( |;)" \
  | (echo "SELECT 'role exists, keeping it' FROM pg_roles WHERE rolname='$ROLE';"; \
     sed -E "s/^CREATE ROLE $ROLE;/DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$ROLE') THEN CREATE ROLE $ROLE; END IF; END \$\$;/") \
  | psql_on "$DST" postgres -q

echo "== database $DB + vector"
printf "CREATE DATABASE %s OWNER %s;\n\\\\c %s\nCREATE EXTENSION vector;\n" "$DB" "$ROLE" "$DB" | psql_on "$DST" postgres -q

echo "== dump $SRC/$DB | restore $DST/$DB"
ssh k8s-main "$K -n postgres exec $SRC -- sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d $DB --format=plain'" \
  | grep -v '^SET transaction_timeout' \
  | psql_on "$DST" "$DB" -q >/dev/null

echo "== verify exact row counts"
COUNTS="select string_agg(format('%s=%s', t, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', t), false, true, '')))[1]::text), ' ' order by t) from (select tablename t from pg_tables where schemaname='public') s;"
A=$(echo "$COUNTS" | psql_on "$SRC" "$DB" -At); B=$(echo "$COUNTS" | psql_on "$DST" "$DB" -At)
echo "src: $A"; echo "dst: $B"
[ -n "$A" ] && [ "$A" = "$B" ] || { echo "row counts differ; app NOT switched (source untouched)"; exit 1; }

echo "== repoint $NS/$SECRET[$KEY]"
OLD=$(ssh k8s-main "$K -n $NS get secret $SECRET -o jsonpath='{.data.$KEY}'" | base64 -d)
NEW=$(printf '%s' "$OLD" | sed -E "s#^([^/:]+)#$NEWHOST#")
echo "   $OLD  ->  $NEW"
ssh k8s-main "$K -n $NS patch secret $SECRET --type merge -p '{\"stringData\":{\"$KEY\":\"$NEW\"}}'"

echo "== restart $NS/$DEPLOY"
ssh k8s-main "$K -n $NS delete pod -l app=$DEPLOY --ignore-not-found --wait=false; $K -n $NS get pods"

echo "== park the source db"
echo "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid <> pg_backend_pid(); ALTER DATABASE $DB RENAME TO ${DB}_moved_$(date +%Y%m%d);" \
  | psql_on "$SRC" postgres -q >/dev/null
echo "done: $DB now on $DST; source kept as ${DB}_moved_$(date +%Y%m%d) on $SRC"
