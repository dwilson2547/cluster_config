"""Generate the Robo pipeline Grafana dashboard ConfigMap.

    python3 monitoring/dashboards/gen_robo_pipeline.py > monitoring/manifests/robo-pipeline-dashboard.yaml

How far behind real time the robo-services telemetry pipeline runs
(robotics/robo-services docs/plans/2026-11-03-processing-lag.md). The services push OTel
metrics to the collector, which Prometheus scrapes:

- robo_upload_lag_seconds: kreceiver receive time minus the end of the frame on the phone
  (phone and network; large after the phone was offline, which is expected);
- robo_pipeline_lag_seconds{stage}: when kreceiver, can-decode, session-tracker or
  vehicle-state finished with a record or frame, minus kreceiver's receive time;
- robo_consumer_backlog{reader,topic}: messages in a topic the reader hasn't consumed;
- robo_frames_total{status}: frames vehicle-state closed, complete / incomplete / empty.

The lags only have data while frames flow (during and just after a drive).
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
panels = []


def nid():
    return len(panels) + 1


def target(ref, expr, legend):
    return {"refId": ref, "expr": expr, "datasource": DS, "range": True, "legendFormat": legend}


def row(title, y):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}})


def timeseries(title, description, targets, x, y, w=12, h=8, unit="s", stack=False, bars=False):
    custom = {"lineWidth": 1, "fillOpacity": 10, "showPoints": "never", "spanNulls": False}
    if stack:
        custom["stacking"] = {"mode": "normal"}
    if bars:
        custom.update(drawStyle="bars", fillOpacity=80)
    panels.append({
        "type": "timeseries", "title": title, "description": description, "id": nid(), "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
        "fieldConfig": {"defaults": {"unit": unit, "custom": custom}, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull", "max"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    })


def stat(title, description, expr, x, y, unit, steps):
    panels.append({
        "type": "stat", "title": title, "description": description, "id": nid(), "datasource": DS,
        "gridPos": {"h": 4, "w": 6, "x": x, "y": y}, "targets": [target("A", expr, "")],
        "fieldConfig": {"defaults": {"unit": unit, "noValue": "idle",
                                     "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "none"},
    })


def q(quantile, metric, by=""):
    group = f"le, {by}" if by else "le"
    return f"histogram_quantile({quantile}, sum by ({group}) (rate({metric}_bucket[$__rate_interval])))"


GOOD_WARN_BAD = lambda warn, bad: [{"color": "green", "value": None}, {"color": "orange", "value": warn},  # noqa: E731
                                   {"color": "red", "value": bad}]

# ── Now ──────────────────────────────────────────────────────────────────────
row("Now", 0)
stat("Pipeline lag p95 (vehicle-state)", "Receive at kreceiver → snapshot row written, last 5 minutes. "
     "Includes vehicle-state's wait for a frame's last sample.",
     'histogram_quantile(0.95, sum by (le) (rate(robo_pipeline_lag_seconds_bucket{stage="vehicle-state"}[5m])))',
     0, 1, "s", GOOD_WARN_BAD(15, 60))
stat("Upload lag p95", "Frame end on the phone → kreceiver, last 5 minutes. High after the phone was offline.",
     'histogram_quantile(0.95, sum by (le) (rate(robo_upload_lag_seconds_bucket[5m])))', 6, 1, "s",
     GOOD_WARN_BAD(10, 60))
stat("Backlog", "Messages not yet read, all readers and topics.", "sum(robo_consumer_backlog)", 12, 1, "short",
     GOOD_WARN_BAD(5000, 50000))
stat("Frames closed / min", "Frames vehicle-state closed in the last minute (any status).",
     "sum(increase(robo_frames_total[1m]))", 18, 1, "short", [{"color": "blue", "value": None}])

# ── Lag ──────────────────────────────────────────────────────────────────────
row("Lag", 5)
timeseries("Pipeline lag p95 by stage", "When each stage finished with a record or frame, minus kreceiver's "
           "receive time. vehicle-state waits for a frame's last sample, so it sits above can-decode.",
           [target("A", q(0.95, "robo_pipeline_lag_seconds", "stage"), "{{stage}}")], 0, 6)
timeseries("Pipeline lag p50 by stage", "As left, median.",
           [target("A", q(0.5, "robo_pipeline_lag_seconds", "stage"), "{{stage}}")], 12, 6)
timeseries("Upload lag", "kreceiver receive time minus the end of the frame on the phone's clock. Phone and "
           "network, not the pipeline.",
           [target("A", q(0.5, "robo_upload_lag_seconds"), "p50"),
            target("B", q(0.95, "robo_upload_lag_seconds"), "p95"),
            target("C", "max(rate(robo_upload_lag_seconds_sum[$__rate_interval]) / "
                        "rate(robo_upload_lag_seconds_count[$__rate_interval]))", "mean")], 0, 14, w=24)

# ── Backlog and frames ───────────────────────────────────────────────────────
row("Backlog and frames", 22)
timeseries("Backlog by reader and topic", "Topic size minus the reader's position, read every 30 s by each "
           "service's consumer watchdog. Climbs during an iggy restart catch-up, then drains.",
           [target("A", "sum by (reader, topic) (robo_consumer_backlog)", "{{reader}} · {{topic}}")],
           0, 23, unit="short")
timeseries("Frames closed by vehicle-state", "Per minute, by how the frame closed: complete (every sample in its "
           "receipt arrived), incomplete, empty (a receipt with no samples).",
           [target("A", "sum by (status) (increase(robo_frames_total[1m]))", "{{status}}")],
           12, 23, unit="short", stack=True, bars=True)

dash = {
    "uid": "robo-pipeline", "title": "Robo pipeline", "tags": ["robo-services", "pipeline"],
    "timezone": "browser", "schemaVersion": 39, "refresh": "30s", "editable": False,
    "time": {"from": "now-3h", "to": "now"},
    "templating": {"list": [{"type": "datasource", "name": "datasource", "label": "Prometheus",
                             "query": "prometheus", "current": {}, "hide": 0}]},
    "annotations": {"list": []},
    "links": [{"title": "Iggy Broker", "type": "link", "url": "/d/iggy-broker"}],
    "panels": panels,
}

body = json.dumps(dash, indent=1)
sys.stdout.write("""# Robo pipeline dashboard: how far behind real time the robo-services telemetry pipeline runs.
# Provisioned by the Grafana sidecar (label grafana_dashboard). Edit the generator, not the JSON:
# python3 monitoring/dashboards/gen_robo_pipeline.py > monitoring/manifests/robo-pipeline-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: robo-pipeline-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  robo-pipeline.json: |
""" + "\n".join("    " + line for line in body.splitlines()) + "\n")
