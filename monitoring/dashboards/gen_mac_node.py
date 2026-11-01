"""Generate the Mac mini inference-node Grafana dashboard ConfigMap (cluster-config monitoring/manifests).

Only uses series the Mac actually exports (job mac-node): macOS node_exporter collectors plus the LM Studio
keepalive's text-file metrics. See monitoring/manifests/mac-monitoring.yaml.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
J = 'job="mac-node"'
panels = []
pid = 0

# macOS "Memory Used" as Activity Monitor reports it: app memory (anonymous minus purgeable) + wired + compressed.
USED = (f'(node_memory_internal_bytes{{{J}}} - node_memory_purgeable_bytes{{{J}}})'
        f' + node_memory_wired_bytes{{{J}}} + node_memory_compressed_bytes{{{J}}}')
TOTAL = f'node_memory_total_bytes{{{J}}}'
DATA_FS = f'{J}, mountpoint="/System/Volumes/Data"'
NIC = f'{J}, device=~"en[0-9]+"'

UPDOWN = {"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}
GREEN_RED = [{"color": "red", "value": None}, {"color": "green", "value": 1}]


def nid():
    global pid
    pid += 1
    return pid


def row(title, y):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}})


def stat(title, expr, x, y, w=3, h=4, steps=None, desc="", unit="none", decimals=0, mappings=None,
         graph=False):
    steps = steps or [{"color": "green", "value": None}]
    panels.append({
        "type": "stat", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "instant": not graph, "datasource": DS}],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "mappings": mappings or [],
                                     "thresholds": {"mode": "absolute", "steps": steps},
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "area" if graph else "none", "textMode": "value",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })


def timeseries(title, targets, x, y, w, h, unit="percent", max_=None, stack=False, desc="", overrides=None,
               min_=0):
    panels.append({
        "type": "timeseries", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit, **({"min": min_} if min_ is not None else {}),
                                     **({"max": max_} if max_ is not None else {}),
                                     "custom": {"lineWidth": 2, "fillOpacity": 30 if stack else 10,
                                                "stacking": {"mode": "normal" if stack else "none"}}},
                        "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    })


def state_timeline(title, targets, x, y, w, h, desc=""):
    panels.append({
        "type": "state-timeline", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": {"mappings": [UPDOWN], "color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": GREEN_RED}}, "overrides": []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                    "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
    })


# ── At a glance ──────────────────────────────────────────────────────────────
row("At a glance", 0)
stat("Exporter", f'max(up{{{J}}}) or vector(0)', 0, 1, steps=GREEN_RED, mappings=[UPDOWN],
     desc="Prometheus can scrape node_exporter on the Mac (192.168.0.30:9100).")
stat("LM Studio server", f'lmstudio_server_up{{{J}}}', 3, 1, steps=GREEN_RED, mappings=[UPDOWN],
     desc="Written by the keepalive each minute: TCP connect to LM Studio's server on :1234.")
stat("Keepalive last ran", f'time() - lmstudio_keepalive_last_run_timestamp_seconds{{{J}}}', 6, 1, unit="s",
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 180}, {"color": "red", "value": 300}],
     desc="Seconds since the launchd keepalive last ran. It runs every minute; MacLMStudioKeepaliveStale fires "
          "past 300 s for 10 min.")
stat("Uptime", f'time() - node_boot_time_seconds{{{J}}}', 9, 1, unit="s",
     steps=[{"color": "orange", "value": None}, {"color": "green", "value": 3600}])
stat("CPU busy", f'100 * (1 - avg(rate(node_cpu_seconds_total{{{J}, mode="idle"}}[$__rate_interval])))',
     12, 1, unit="percent", graph=True,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 70}, {"color": "red", "value": 90}])
stat("Memory used", f'100 * ({USED}) / {TOTAL}', 15, 1, unit="percent", graph=True,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 75}, {"color": "red", "value": 90}],
     desc="Activity Monitor's 'Memory Used' (app + wired + compressed) as a share of unified memory. "
          "Models must fit here alongside macOS.")
stat("Swap used", f'node_memory_swap_used_bytes{{{J}}}', 18, 1, unit="bytes", decimals=1,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 2 * 1024**3},
            {"color": "red", "value": 4 * 1024**3}])
stat("Disk free", f'node_filesystem_avail_bytes{{{DATA_FS}}}', 21, 1, unit="bytes", decimals=0,
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 30 * 1000**3},
            {"color": "green", "value": 60 * 1000**3}],
     desc="Free space in the APFS container (Data volume), where model files live.")

# ── LM Studio ────────────────────────────────────────────────────────────────
row("LM Studio", 5)
state_timeline("Availability", [(f'up{{{J}}}', "exporter"), (f'lmstudio_server_up{{{J}}}', "LM Studio server")],
               0, 6, 16, 5, desc="Gaps in 'exporter' mean the Mac (or node_exporter) was unreachable.")
timeseries("Keepalive age", [(f'time() - lmstudio_keepalive_last_run_timestamp_seconds{{{J}}}', "age")],
           16, 6, 8, 5, unit="s")

# ── CPU ──────────────────────────────────────────────────────────────────────
row("CPU", 11)
timeseries("CPU by mode",
           [(f'100 * sum by (mode) (rate(node_cpu_seconds_total{{{J}, mode!="idle"}}[$__rate_interval]))'
             f' / scalar(count(node_cpu_seconds_total{{{J}, mode="idle"}}))', "{{mode}}")],
           0, 12, 8, 8, max_=100, stack=True)
timeseries("CPU per core",
           [(f'100 * (1 - rate(node_cpu_seconds_total{{{J}, mode="idle"}}[$__rate_interval]))', "cpu {{cpu}}")],
           8, 12, 8, 8, max_=100)
timeseries("Load average",
           [(f'node_load1{{{J}}}', "1m"), (f'node_load5{{{J}}}', "5m"), (f'node_load15{{{J}}}', "15m"),
            (f'count(node_cpu_seconds_total{{{J}, mode="idle"}})', "cores")],
           16, 12, 8, 8, unit="short",
           overrides=[{"matcher": {"id": "byName", "options": "cores"},
                       "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}},
                                      {"id": "custom.fillOpacity", "value": 0},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}])

# ── Memory ───────────────────────────────────────────────────────────────────
row("Memory", 20)
timeseries("Unified memory",
           [(f'node_memory_wired_bytes{{{J}}}', "wired"),
            (f'node_memory_internal_bytes{{{J}}} - node_memory_purgeable_bytes{{{J}}}', "app"),
            (f'node_memory_compressed_bytes{{{J}}}', "compressed"),
            (f'node_memory_inactive_bytes{{{J}}}', "inactive (cache)"),
            (f'node_memory_free_bytes{{{J}}}', "free")],
           0, 21, 12, 9, unit="bytes", stack=True,
           desc="Stacked to total unified memory. wired + app + compressed = Activity Monitor's 'Memory Used'.",
           overrides=[{"matcher": {"id": "byName", "options": "free"},
                       "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "transparent"}},
                                      {"id": "custom.lineWidth", "value": 0}]}])
timeseries("Swap",
           [(f'node_memory_swap_used_bytes{{{J}}}', "used"), (f'node_memory_swap_total_bytes{{{J}}}', "allocated")],
           12, 21, 6, 9, unit="bytes")
timeseries("Swap traffic",
           [(f'rate(node_memory_swapped_in_bytes_total{{{J}}}[$__rate_interval])', "in"),
            (f'-rate(node_memory_swapped_out_bytes_total{{{J}}}[$__rate_interval])', "out")],
           18, 21, 6, 9, unit="Bps", min_=None,
           desc="Sustained swap-out during inference means the model plus context doesn't fit in memory.")

# ── Disk & network ───────────────────────────────────────────────────────────
row("Disk & network", 30)
timeseries("Disk throughput",
           [(f'rate(node_disk_read_bytes_total{{{J}}}[$__rate_interval])', "read {{device}}"),
            (f'-rate(node_disk_written_bytes_total{{{J}}}[$__rate_interval])', "write {{device}}")],
           0, 31, 8, 8, unit="Bps", min_=None, desc="Reads spike when a model is loaded from disk.")
timeseries("Network",
           [(f'rate(node_network_receive_bytes_total{{{NIC}}}[$__rate_interval]) > 0', "rx {{device}}"),
            (f'-rate(node_network_transmit_bytes_total{{{NIC}}}[$__rate_interval]) < 0', "tx {{device}}")],
           8, 31, 8, 8, unit="Bps", min_=None)
timeseries("Disk space",
           [(f'node_filesystem_size_bytes{{{DATA_FS}}} - node_filesystem_avail_bytes{{{DATA_FS}}}', "used"),
            (f'node_filesystem_size_bytes{{{DATA_FS}}}', "size")],
           16, 31, 8, 8, unit="bytes")

dashboard = {
    "uid": "mac-mini",
    "title": "Mac mini (inference node)",
    "tags": ["mac", "gpu-scheduler", "inference"],
    "timezone": "browser",
    "schemaVersion": 39,
    "refresh": "30s",
    "editable": False,
    "time": {"from": "now-6h", "to": "now"},
    "templating": {"list": [{"type": "datasource", "name": "datasource", "label": "Prometheus",
                             "query": "prometheus", "current": {}, "hide": 0}]},
    "annotations": {"list": []},
    "panels": panels,
}

HEADER = """\
# Mac mini dashboard: gpu-scheduler's remote inference node (host + LM Studio keepalive metrics, job mac-node).
# Provisioned by the Grafana sidecar (label grafana_dashboard); edit the generator, not the JSON:
# monitoring/dashboards/gen_mac_node.py > monitoring/manifests/mac-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mac-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  mac-mini.json: |
"""

body = json.dumps(dashboard, indent=1)
sys.stdout.write(HEADER + "".join("    " + line + "\n" for line in body.splitlines()))
