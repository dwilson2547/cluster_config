# Mis-indented backend port fields caused the Todo Store ingress sync to fail and left the host on Traefik's default 404.

**Date:** 2026-05-25  
**Component:** `ai-services/deployment.yml` — `Ingress ingress-todo-store`  
**Severity:** High — the API and UI pods were healthy, but the public hostname could not route to them, so the service looked deployed while remaining inaccessible.

---

## Observed symptom

`todo-store-api` and `todo-store-ui` deployed successfully in the `ai-services` namespace, but `todo.ai-services.local` returned Traefik's default 404 and `kubectl get ingress -n ai-services ingress-todo-store` returned `NotFound`. ArgoCD reported the app as `OutOfSync` with the sync error `Ingress.networking.k8s.io "ingress-todo-store" is invalid: [spec.rules[0].http.paths[0].backend: Required value: port name or number is required, spec.rules[0].http.paths[1].backend: Required value: port name or number is required]`.

---

## Root cause

### YAML indentation detached `number:` from `backend.service.port`

The newly added Todo Store ingress had the `number:` fields aligned with `port:` instead of nested under it. That produced an invalid Kubernetes Ingress manifest even though the rest of the Todo Store resources applied cleanly.

```yaml
      - path: /api/
        pathType: Prefix
        backend:
          service:
            name: todo-store-api
            port:
            number: 8003
```

Because the Ingress object was rejected at admission time, Traefik never received a route for `todo.ai-services.local`.

### ArgoCD kept retrying the broken revision until a corrected manifest was pushed

ArgoCD detected the new repository revision, but the active sync operation kept retrying against the invalid ingress definition. The app stayed `OutOfSync` and the hostname continued to fall through to the ingress controller's default backend until the corrected manifest was both pushed and applied.

---

## Troubleshooting steps taken

1. **Checked the live ingress resource** — confirmed the hostname problem was not DNS-only because `kubectl -n ai-services get ingress ingress-todo-store` returned `NotFound`.

2. **Checked ArgoCD application status** — ruled in a manifest error when the `ai-services` application reported the backend `port name or number is required` validation failure for `ingress-todo-store`.

3. **Compared the rendered ingress structure to the applied YAML** — identified the mis-indented `number:` keys under `backend.service.port`, corrected them, pushed the fix, and reapplied the corrected manifest so the route could be created immediately.

---

## Fix

### `ai-services/deployment.yml` — nested the backend service port numbers correctly

The fix indented each `number:` field beneath its corresponding `port:` mapping so Kubernetes accepted the Ingress resource.

```yaml
      - path: /api/
        pathType: Prefix
        backend:
          service:
            name: todo-store-api
            port:
              number: 8003
```

The same correction was applied to the UI backend on port 80.

### Cluster rollout — refreshed the GitOps app and applied the corrected manifest once

After the corrected revision was pushed to `cluster_config`, the `ai-services` ArgoCD application was refreshed and the corrected manifest was applied so `ingress-todo-store` could be created immediately. Final verification showed `todo.ai-services.local` resolving to `192.168.0.60`, `/api/health` returning `{"status":"ok"}`, and the UI serving HTML on the root path.

---

## Files changed

- `ai-services/deployment.yml` — `Ingress ingress-todo-store`
- `CHANGELOG.md` — 2026-05-25 fix entry
- `docs/issues/2026_05_25_todo_store_ingress_port_indentation.md` — incident record
