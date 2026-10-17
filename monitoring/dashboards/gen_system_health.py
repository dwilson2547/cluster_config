"""Generate the System Health Grafana dashboard ConfigMap (cluster-config monitoring/manifests)."""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
panels = []
pid = 0


def nid():
    global pid
    pid += 1
    return pid


def row(title, y):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}})


def stat(title, expr, x, y, w=3, h=4, steps=None, desc="", unit="none"):
    steps = steps or [{"color": "green", "value": None}, {"color": "red", "value": 1}]
    panels.append({
        "type": "stat", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "instant": True, "datasource": DS}],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 0,
                                     "thresholds": {"mode": "absolute", "steps": steps},
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "none", "textMode": "value",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })


def table(title, expr, x, y, w, h, exclude=(), rename=None, unit="none", value_name="Value",
          sort=None, desc="", overrides=None, steps=None):
    ex = {k: True for k in ("Time", "__name__", "job", "instance", "endpoint", "service", "pod_template_hash",
                            "container", "metrics_path", "uid", "prometheus", "alertstate", *exclude)}
    rn = dict(rename or {})
    rn["Value"] = value_name
    p = {
        "type": "table", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "instant": True, "format": "table", "datasource": DS}],
        "transformations": [{"id": "organize", "options": {"excludeByName": ex, "renameByName": rn}}],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"align": "auto"},
                                     "thresholds": {"mode": "absolute",
                                                    "steps": steps or [{"color": "text", "value": None}]}},
                        "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm",
                    "sortBy": [{"displayName": sort[0], "desc": sort[1]}] if sort else []},
    }
    panels.append(p)


def timeseries(title, expr, legend, x, y, w, h, unit="percent", max_=None):
    panels.append({
        "type": "timeseries", "title": title, "id": nid(), "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "legendFormat": legend, "datasource": DS}],
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, **({"max": max_} if max_ else {}),
                                     "custom": {"lineWidth": 2, "fillOpacity": 10}}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    })


NODE = '* on(instance) group_left(nodename) node_uname_info'
BACKUP_NS = 'postgres|secrets-backup|offsite-backup'
WARN1 = [{"color": "green", "value": None}, {"color": "orange", "value": 1}]

# ── At a glance ──────────────────────────────────────────────────────────────
row("At a glance", 0)
stat("Critical alerts", 'count(ALERTS{alertstate="firing", severity="critical"}) or vector(0)', 0, 1)
stat("Warnings", 'count(ALERTS{alertstate="firing", severity="warning"}) or vector(0)', 3, 1, steps=WARN1)
stat("Nodes not ready",
     'count(kube_node_info) - sum(kube_node_status_condition{condition="Ready", status="true"})', 6, 1)
stat("Pods stuck", '(count(kube_pod_container_status_waiting_reason{reason=~"CrashLoopBackOff|ImagePullBackOff|'
     'ErrImagePull|CreateContainerConfigError|CreateContainerError"} == 1) or vector(0))'
     ' + (count(kube_pod_status_phase{phase=~"Pending|Unknown"} == 1) or vector(0))', 9, 1,
     desc="Containers crashlooping / failing to start, plus pods Pending or Unknown.")
stat("Restarts (1h)", 'round(sum(increase(kube_pod_container_status_restarts_total[1h])))', 12, 1, steps=WARN1)
stat("Targets down", 'count(up == 0) or vector(0)', 15, 1, desc="Prometheus scrape targets not answering.")
stat("Backups stale",
     f'(count((time() - kube_cronjob_status_last_successful_time{{namespace=~"postgres|secrets-backup", '
     f'cronjob!~".*restore-test.*"}}) > 26*3600) or vector(0))'
     f' + (count((time() - kube_cronjob_status_last_successful_time{{namespace="offsite-backup"}}) > 8*86400)'
     f' or vector(0))', 18, 1,
     desc="Nightly backups with no success in 26h, or the weekly offsite backup with none in 8 days.")
stat("Scrape jobs degraded", 'count(scrape_job_phase{phase="Degraded"} == 1) or vector(0)', 21, 1,
     steps=WARN1, desc="scrape-job-manager jobs whose recent runs failed (dev and prod).")

# ── Alerts ───────────────────────────────────────────────────────────────────
row("Firing alerts", 5)
table("Firing alerts (Watchdog/InfoInhibitor hidden)",
      'ALERTS{alertstate="firing", alertname!~"Watchdog|InfoInhibitor"}', 0, 6, 24, 7,
      exclude=("Value",), sort=("severity", False))

# ── Nodes ────────────────────────────────────────────────────────────────────
row("Nodes", 13)
timeseries("CPU used", f'100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{{mode="idle"}}[5m]))) {NODE}',
           "{{nodename}}", 0, 14, 8, 8, max_=100)
timeseries("Memory used", f'100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) {NODE}',
           "{{nodename}}", 8, 14, 8, 8, max_=100)
timeseries("Root disk used", f'100 * (1 - node_filesystem_avail_bytes{{mountpoint="/"}} '
           f'/ node_filesystem_size_bytes{{mountpoint="/"}}) {NODE}', "{{nodename}}", 16, 14, 8, 8, max_=100)

# ── Storage ──────────────────────────────────────────────────────────────────
row("Volumes", 22)
table("Volume use (NFS volumes report their whole share)",
      '100 * max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes{job="kubelet"})'
      ' / max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{job="kubelet"})',
      0, 23, 12, 9, unit="percent", value_name="Used", sort=("Used", True),
      overrides=[{"matcher": {"id": "byName", "options": "Used"},
                  "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
                                 {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                     {"color": "green", "value": None}, {"color": "orange", "value": 80},
                                     {"color": "red", "value": 90}]}}]}])

# ── Backups ──────────────────────────────────────────────────────────────────
table("Backups: last success",
      f'kube_cronjob_status_last_successful_time{{namespace=~"{BACKUP_NS}"}} * 1000', 12, 23, 12, 9,
      unit="dateTimeFromNow", value_name="Last success", sort=("Last success", False),
      desc="Nightly: dumps, buckets, volumes, tracks, secrets. Weekly: offsite (MEGA), restore tests.")

# ── Workloads ────────────────────────────────────────────────────────────────
row("Workloads", 32)
table("Deployments / StatefulSets short of replicas",
      '(kube_deployment_spec_replicas > 0) - kube_deployment_status_replicas_available > 0'
      ' or (kube_statefulset_replicas > 0) - kube_statefulset_status_replicas_ready > 0',
      0, 33, 12, 8, value_name="Missing", sort=("Missing", True))
table("Most restarted containers (24h)",
      'topk(10, round(increase(kube_pod_container_status_restarts_total[24h])) > 0)',
      12, 33, 12, 8, value_name="Restarts", sort=("Restarts", True),
      rename={"container": "container"})

# ── Scrapers ─────────────────────────────────────────────────────────────────
row("Scrapers (scrape-job-manager)", 41)
table("Jobs failing", 'scrape_job_consecutive_failures > 0', 0, 42, 12, 9,
      exclude=("namespace", "pod"), rename={"exported_namespace": "namespace"},
      value_name="Failures in a row", sort=("Failures in a row", True))
panels.append({
    "type": "bargauge", "title": "Jobs by phase", "id": nid(), "datasource": DS,
    "gridPos": {"h": 9, "w": 6, "x": 12, "y": 42},
    "targets": [{"refId": "A", "expr": 'count by (phase) (scrape_job_phase == 1)', "instant": True,
                 "legendFormat": "{{phase}}", "datasource": DS}],
    "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": "blue"}},
                    "overrides": [
                        {"matcher": {"id": "byName", "options": "Healthy"},
                         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
                        {"matcher": {"id": "byName", "options": "Degraded"},
                         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
                        {"matcher": {"id": "byName", "options": "Disabled"},
                         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}}]}]},
    "options": {"orientation": "horizontal", "displayMode": "basic",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
})
stat("Operator last tick", 'time() - scrape_operator_last_tick_timestamp_seconds', 18, 42, w=6, h=9,
     unit="s", steps=[{"color": "green", "value": None}, {"color": "orange", "value": 120},
                      {"color": "red", "value": 600}],
     desc="Seconds since scrape-job-manager's reconcile loop last ran.")

dash = {
    "uid": "system-health", "title": "System Health", "tags": ["cluster", "overview"],
    "timezone": "browser", "schemaVersion": 39, "refresh": "1m", "editable": False,
    "time": {"from": "now-6h", "to": "now"},
    "templating": {"list": [{"type": "datasource", "name": "datasource", "label": "Prometheus",
                             "query": "prometheus", "current": {}, "hide": 0}]},
    "annotations": {"list": []},
    "panels": panels,
}

body = json.dumps(dash, indent=1)
header = """# System Health dashboard: cluster state at a glance (alerts, nodes, volumes, backups, workloads, scrapers).
# Provisioned by the Grafana sidecar (label grafana_dashboard); edit the generator, not the JSON:
# monitoring/dashboards/gen_system_health.py > monitoring/manifests/system-health-dashboard.yaml
"""
cm = header + """apiVersion: v1
kind: ConfigMap
metadata:
  name: system-health-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  system-health.json: |
""" + "\n".join("    " + line for line in body.splitlines()) + "\n"
sys.stdout.write(cm)
