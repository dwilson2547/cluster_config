# Context Store rename caused ingress 404 because ArgoCD was still reconciling the old ai-playbooks manifests

**Date:** 2026-05-24  
**Component:** `ai-services/deployment.yml` — context-store ingress/service/deployment rename, `homepage/homepage.yaml` — AI Services entry  
**Severity:** High — the renamed public hostname returned a 404 and the live cluster drifted back to the old service names under automated reconciliation.

---

## Observed symptom

After renaming the service from ai-playbooks to context-store, `http://context-store.ai-services.local` returned `404 page not found` while other AI service hosts such as `notes.ai-services.local` and `docs.ai-services.local` still worked. DNS already resolved the new hostname to the ingress IP, so the request reached Traefik but did not match any live ingress rule for the new host.

---

## Root cause

### ArgoCD was still applying the old committed ai-playbooks manifests

The live `ai-services` ArgoCD application still tracked `main` at a revision whose manifests defined only `ingress-ai-playbooks`, `ai-playbooks-api`, and `ai-playbooks-ui`. Because the app has `automated.prune: true` and `selfHeal: true`, deleting the old resources caused ArgoCD to recreate them immediately from Git.

```yaml
spec:
  source:
    repoURL: git@github.com:dwilson2547/cluster_config.git
    path: ai-services
    targetRevision: main
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### DNS and ingress state drifted apart during the rename

The new hostname already resolved to the cluster ingress IP, but the live cluster still only exposed the old playbooks ingress. That mismatch meant the request reached Traefik successfully and then fell through to the default 404 handler because no ingress rule matched `context-store.ai-services.local`.

### Renaming the PVC would have risked data loss during the rollout

The original manifest rename changed the data claim from `pvc-ai-playbooks` to `pvc-context-store`. Applying that change live would have provisioned a new empty claim instead of reusing the existing document store. The fix preserved the legacy claim name while renaming the user-facing workload resources.

---

## Troubleshooting steps taken

1. **Checked the renamed host directly** — `context-store.ai-services.local` resolved to `192.168.0.60`, but both `/` and `/api/instructions` returned ingress-level 404 responses, which ruled out a DNS failure and pointed at missing live routing.

2. **Compared live ingresses in the cluster** — `kubectl get ingress -n ai-services` showed `ingress-ai-notes`, `ingress-ai-playbooks`, and `ingress-ai-tool-docs`, but no `ingress-context-store`, which confirmed the live cluster had not picked up the rename.

3. **Inspected the ArgoCD application state** — the `ai-services` application was configured for automated prune and self-heal against `main`, which ruled in Git as the source of truth and explained why deleted `ai-playbooks` resources were recreated immediately.

4. **Verified live service backends after manual apply** — once the renamed resources were applied, `kubectl describe ingress ingress-context-store -n ai-services` showed healthy backend endpoints and the host began returning `200 OK`, which confirmed the renamed manifests themselves were valid.

---

## Fix

### `ai-services/deployment.yml` — rename public resources while preserving the existing PVC

The ai-playbooks ConfigMap, Deployments, Services, and Ingress were renamed to `context-store-*`, and the Docker images were updated to `dwilson2547/context-store-api:latest` and `dwilson2547/context-store-ui:latest`. The persistent claim reference stayed on `pvc-ai-playbooks` so the existing `/data` contents remain attached after the rollout.

```yaml
metadata:
  name: context-store-api
...
      - image: dwilson2547/context-store-api:latest
...
        persistentVolumeClaim:
          claimName: pvc-ai-playbooks
```

### `homepage/homepage.yaml` — update the dashboard link

The AI Services card was renamed from `AI Playbooks` to `Context Store` and now points to `http://context-store.ai-services.local`, matching the renamed ingress host.

### Live rollout — apply renamed resources and verify the new host

The old `ai-playbooks` ingress, services, deployments, and UI ConfigMap were removed, then the updated manifests were applied and the new `context-store` deployments were rolled out. After the new ingress propagated, `context-store.ai-services.local` returned `200 OK` and `/api/instructions` served the Context Store API guide.

---

## Files changed

- `ai-services/deployment.yml` — context-store rename and legacy PVC preservation
- `homepage/homepage.yaml` — Context Store homepage entry
- `docs/issues/2026_05_24_context_store_ingress_404.md` — rollout incident record
- `CHANGELOG.md` — fix entry linking to the issue document
