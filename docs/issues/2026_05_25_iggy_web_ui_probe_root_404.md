# Iggy Web UI probe path targeted `/`, leaving the pod unready and the ingress returning 503

**Date:** 2026-05-25  
**Component:** `pub-sub/deployment.yml` — `Deployment/iggy-web-ui`, `homepage/homepage.yaml` — `services.yaml`  
**Severity:** Medium — the broker stayed up, but the UI never became ready and the published host was unusable through the ingress.

---

## Observed symptom

The `iggy-web-ui` pod in the `pub-sub` namespace stayed in `Running` but never became `Ready`, and requests to `http://iggy-web.pub-sub.local` returned `503 Service Unavailable` through Traefik. Pod events showed repeated readiness and liveness probe failures with `HTTP probe failed with statuscode: 404`, and the container logs showed repeated `GET /` requests returning `404`.

---

## Root cause

### Standalone Iggy Web UI does not serve `/`

The `apache/iggy-web-ui:0.3.0` container was healthy, but it did not expose a successful response at the root path. The app returned `200 OK` for `/auth/sign-in`, while `/` returned `404 Not Found`.

```text
[404] GET /
```

Because the Deployment used `/` for both readiness and liveness probes, Kubernetes never marked the pod ready even though the UI process was running.

### Ingress depended on pod readiness

The ingress and Service wiring were correct, but Traefik had no ready backend endpoints to route to because the pod remained unready. That turned a probe-path mistake inside the Deployment into a visible `503` at the public hostname.

---

## Troubleshooting steps taken

1. **Checked live pub-sub resources** — confirmed the broker pod was ready, the UI pod was running but unready, and the ingress/service objects existed for both `iggy.pub-sub.local` and `iggy-web.pub-sub.local`.

2. **Described the failing UI pod** — verified repeated readiness and liveness probe failures with `404` responses instead of image-pull, scheduling, or crash-loop problems.

3. **Probed routes inside the container** — confirmed `/` returned `404 Not Found` while `/auth/sign-in` returned `200 OK`, isolating the problem to the probe path rather than the container image, service, or ingress.

4. **Checked external host behavior** — observed `503 Service Unavailable` from the published host while the pod was unready, confirming ingress availability depended on fixing readiness first.

---

## Fix

### `pub-sub/deployment.yml` — point health probes at the real UI entry route

Changed the `iggy-web-ui` readiness and liveness probes from `/` to `/auth/sign-in`, which is the route the standalone UI actually serves successfully.

```yaml
readinessProbe:
  httpGet:
    path: /auth/sign-in
    port: http

livenessProbe:
  httpGet:
    path: /auth/sign-in
    port: http
```

This allows Kubernetes to mark the pod ready and restores ingress routing to the UI.

### `homepage/homepage.yaml` — link directly to the working entry path

Updated the homepage dashboard link to use `http://iggy-web.pub-sub.local/auth/sign-in` instead of the root host, so the dashboard opens the working login page directly instead of a 404 root route.

```yaml
href: http://iggy-web.pub-sub.local/auth/sign-in
```

---

## Files changed

- `pub-sub/deployment.yml` — `Deployment/iggy-web-ui`
- `homepage/homepage.yaml` — `services.yaml`
