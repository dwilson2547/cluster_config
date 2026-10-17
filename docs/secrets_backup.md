# Secrets backup

Every Secret in the cluster is hand-applied (CLAUDE.md, "Secret Management"), so git alone cannot rebuild the
cluster. `secrets-backup/` exports them nightly, encrypted, to the Unraid backup share.

## What runs

CronJob `backup-secrets` (namespace `secrets-backup`, 03:00 ET): `kubectl get secrets -A -o json`, piped straight
into `age -r <public key>`, so plaintext never touches disk.

```
/backups/secrets/<stamp>.json.age     one file per night, 28 days kept
/backups/secrets/.last-success
```

Left out: service-account tokens and Helm release records (`sh.helm.release.v1`), both recreated by the cluster
and Argo. Alerts (failed job, no success in 26h, suspended) mail like the postgres backup alerts
(`secrets-backup/alerts.yaml`).

The age public key is in `secrets-backup/backup.yaml` (`AGE_RECIPIENT`). The private key is held by the user, off
the cluster and off the backup share; without it no export can be read. To rotate: generate a new keypair, change
`AGE_RECIPIENT`, and keep the old private key until the last export made with it is pruned (28 days).

## Restore

On a machine with the private key (`key.txt`), `age`, `jq` and a kubeconfig. `age -d` writes plaintext to stdout:
pipe it, don't save it.

```bash
F=/path/to/<stamp>.json.age
STRIP='.items |= map(del(.metadata.uid, .metadata.resourceVersion, .metadata.creationTimestamp,
  .metadata.managedFields, .metadata.ownerReferences,
  .metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"]))'

# list what is in an export (names only)
age -d -i key.txt "$F" | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)"'

# one secret
age -d -i key.txt "$F" | jq "$STRIP"' | .items |= map(select(.metadata.namespace=="NS" and .metadata.name=="NAME"))' \
  | kubectl apply -f -

# one namespace
age -d -i key.txt "$F" | jq "$STRIP"' | .items |= map(select(.metadata.namespace=="NS"))' | kubectl apply -f -
```

The uid/resourceVersion fields must go: the API refuses to create an object that already carries a
resourceVersion.

## Rebuilding a cluster

1. Cluster up, with the microk8s addons the cluster was built with, and the NFS CSI driver (the backup share has to
   be mountable to read the exports).
2. Namespaces for the secrets you restore: `age -d -i key.txt "$F" | jq -r '.items[].metadata.namespace' | sort -u
   | xargs -n1 kubectl create namespace` (existing ones just error).
3. Restore all secrets: the "one namespace" command without the namespace filter. Secrets owned by an operator
   (cert-manager certificates, operator-generated credentials) come back as plain Secrets; the operator adopts or
   reissues them.
4. Argo: install it, then `kubectl apply -f bootstrap/apps.yaml`. Every Application syncs from git and finds its
   secrets already present.
5. Data: postgres dumps (`docs/postgres_backup.md`) and object buckets (same doc, "Object-store buckets").
