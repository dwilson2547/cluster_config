# authentik patterns (2026.8)

Config lives in `authentik/values.yaml` (Helm) and `authentik/blueprints/` (flows, sources,
notifications as blueprints, mounted via `blueprints.configMaps`).

## Blueprints

- **Validate before pushing** with authentik's own importer, in the worker pod. It runs in a
  rolled-back transaction, so nothing is written:
  `kubectl -n authentik cp <file> <worker>:/tmp/x.yaml`, then
  `ak shell -c 'from authentik.blueprints.v1.importer import Importer; print(Importer.from_string(open("/tmp/x.yaml").read()).validate())'`.
  Blueprints using `!Env` need the variables set for the check (`env FOO=dummy ak shell ...`).
- **Validation does not catch unknown attrs.** The importer drops fields it does not recognise
  without a warning. Take field names from `/blueprints/schema.json` in the running image, not from
  the shipped example blueprints: `events-default.yaml` still uses `group` on notification rules,
  which 2026.8 renamed to `destination_group`, so those rules are created with no recipients.
- **A newly mounted ConfigMap may not be picked up until the next scheduled discovery.** After the
  first rollout that added the mount, no instance existed for the files. Trigger it:
  `ak shell -c 'from authentik.blueprints.v1.tasks import blueprints_discovery; blueprints_discovery.send()'`.
  Edits to an already-discovered file do get applied once kubelet syncs the ConfigMap (~1 min).
- Check results through the ORM (`ak shell`), not raw SQL: the table layout uses multi-table
  inheritance and the join columns are not obvious.

## Source enrollment flows

- **Never end a source (Google/OAuth) enrollment flow with a Deny stage.** authentik appends
  `PostSourceStage` after the flow's own stages; it is what saves the user-to-Google connection
  (`core/sources/flow_manager.py`, `get_stages_to_append`). A Deny stage aborts before it, so the
  user exists but no connection does, and with `user_matching_mode: identifier` the next Google
  sign-in cannot find them. To stop without signing in, let the flow complete and simply omit the
  User Login stage; an info prompt (`alert_info` field) can carry the message.

## Client IPs behind Cloudflare

Two layers both have to trust the hop in front of them, or authentik logs the wrong address:
`traefik-public` needs `externalTrafficPolicy: Local` plus Cloudflare ranges in
`forwardedHeaders.trustedIPs` (else: a node IP), and authentik needs the same ranges in
`AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS` (else: the Cloudflare edge IP). Check with the `"remote"`
field in the server log against the requester's real public IP.
