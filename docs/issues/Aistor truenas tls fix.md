# AIStor on TrueNAS — TLS Handshake Timeout on container-utils Pull

## Symptom

AIStor app install via TrueNAS Apps UI fails mid-pull with:

```
permissions Error Get "https://registry-1.docker.io/v2/ixsystems/container-utils/manifests/sha256:46eba20714c1cc6784f60e245c32c33a2d9f616e47d804694a9854248c89a992": net/http: TLS handshake timeout
Error response from daemon: Get "https://registry-1.docker.io/v2/ixsystems/container-utils/manifests/sha256:46eba20714c1cc6784f60e245c32c33a2d9f616e47d804694a9854248c89a992": net/http: TLS handshake timeout
```

The main `aistor` image pulls successfully; only the `ixsystems/container-utils` sidecar fails.

## Root Cause

TLS handshake timeout (not a DNS failure) caused by an MTU mismatch on Docker's internal bridge network. The TCP handshake completes but the TLS ClientHello packet gets fragmented and silently dropped in transit — typically triggered when the Docker bridge MTU (default 1500) exceeds the effective MTU of the host network path.

Can also occur as a transient Docker Hub connectivity blip.

## Fix

### Step 1 — Try a direct pull first

SSH into the TrueNAS box and pull the image manually:

```bash
docker pull ixsystems/container-utils@sha256:46eba20714c1cc6784f60e245c32c33a2d9f616e47d804694a9854248c89a992
```

If this succeeds, the image is now in the local cache and the TrueNAS app installer will use it. Retry the app install — no further changes needed.

If the direct pull also hangs, proceed to Step 2.

### Step 2 — Fix Docker bridge MTU

Check current MTU:

```bash
docker network inspect bridge | grep -i mtu
ip link show docker0
```

If set to 1500, reduce it. A safe value is **1450**; use **1400** if your network path includes VLAN tagging.

Edit `/etc/docker/daemon.json`:

```json
{
  "mtu": 1450
}
```

Restart Docker and retry.

> **Note:** On TrueNAS Scale, direct edits to `daemon.json` may be overwritten on reboot. If that happens, apply the MTU via a TrueNAS System Tunable or set it through the network interface settings in the UI.

## Notes

- AIStor app version at time of issue: `RELEASE.2026-04-11T03-20-12Z` (TrueNAS Stable train v1.1.8)
- The `ixsystems/container-utils` image is a sidecar pulled separately from the main `quay.io/minio/aistor/minio` image
- This error pattern (main image succeeds, sidecar fails) is a reliable indicator of MTU fragmentation rather than auth or DNS issues