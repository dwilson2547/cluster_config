"""Generate the Ampere Altra Grafana dashboard ConfigMap (cluster-config monitoring/manifests).

Two jobs, both scraped by monitoring/manifests/ampere-monitoring.yaml: ampere-node (node_exporter) and ampere-process
(process-exporter, every process grouped by executable name; Python split by script or module).

CPU is shown in cores, not percent: on 128 cores one single-threaded process at full speed is under 1% of the box,
but it reads as 1.0 core here, and that is what keeps the box from being idle.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
J = 'job="ampere-node"'
P = 'job="ampere-process"'
panels = []
pid = 0

CORES = f'count(node_cpu_seconds_total{{{J}, mode="idle"}})'
BUSY = f'({CORES} - sum(rate(node_cpu_seconds_total{{{J}, mode="idle"}}[$__rate_interval])))'
IDLE_BELOW = 0.5  # busy cores; idle background measured at 0.03 (2026-11-10)
USED = f'node_memory_MemTotal_bytes{{{J}}} - node_memory_MemAvailable_bytes{{{J}}}'
TOTAL = f'node_memory_MemTotal_bytes{{{J}}}'
ROOT_FS = f'{J}, mountpoint="/"'
NIC = f'{J}, device=~"en.+"'

LIVE = f'and on (groupname) (namedprocess_namegroup_num_procs{{{P}}} > 0)'
PROC_CPU = f'sum by (groupname) (rate(namedprocess_namegroup_cpu_seconds_total{{{P}}}[$__rate_interval]))'
PROC_RSS = f'namedprocess_namegroup_memory_bytes{{{P}, memtype="resident"}}'

UPDOWN = {"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}
IDLEBUSY = {"type": "value", "options": {"0": {"text": "IDLE", "color": "blue"}, "1": {"text": "BUSY", "color": "green"}}}
GREEN_RED = [{"color": "red", "value": None}, {"color": "green", "value": 1}]


def nid():
    global pid
    pid += 1
    return pid


def row(title, y):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}})


def stat(title, expr, x, y, w=3, h=4, steps=None, desc="", unit="none", decimals=0, mappings=None,
         graph=False, legend="", text="value"):
    steps = steps or [{"color": "green", "value": None}]
    panels.append({
        "type": "stat", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "instant": not graph, "legendFormat": legend, "datasource": DS}],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "mappings": mappings or [],
                                     "thresholds": {"mode": "absolute", "steps": steps},
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "area" if graph else "none", "textMode": text,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })


def timeseries(title, targets, x, y, w, h, unit="short", max_=None, stack=False, desc="", overrides=None,
               min_=0, decimals=None):
    panels.append({
        "type": "timeseries", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit, **({"min": min_} if min_ is not None else {}),
                                     **({"max": max_} if max_ is not None else {}),
                                     **({"decimals": decimals} if decimals is not None else {}),
                                     "custom": {"lineWidth": 2, "fillOpacity": 30 if stack else 10,
                                                "stacking": {"mode": "normal" if stack else "none"}}},
                        "overrides": overrides or []},
        "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull", "max"],
                               "sortBy": "Max", "sortDesc": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    })


def col(name, unit, decimals=None, width=None):
    props = [{"id": "unit", "value": unit}]
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    if width:
        props.append({"id": "custom.width", "value": width})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def process_table(x, y, w, h):
    queries = [
        ("cpu", f'{PROC_CPU} {LIVE}'),
        ("rss", f'{PROC_RSS} {LIVE}'),
        ("threads", f'namedprocess_namegroup_num_threads{{{P}}} {LIVE}'),
        ("procs", f'namedprocess_namegroup_num_procs{{{P}}} > 0'),
        ("age", f'time() - namedprocess_namegroup_oldest_start_time_seconds{{{P}}} {LIVE}'),
    ]
    names = {"groupname": "Process", "Value #cpu": "CPU (cores)", "Value #rss": "RAM (RSS)",
             "Value #threads": "Threads", "Value #procs": "Processes", "Value #age": "Running for"}
    panels.append({
        "type": "table", "title": "Processes now", "id": nid(), "datasource": DS,
        "description": "Every live process group, by executable name (Python by script or module). CPU in cores: "
                       "a single-threaded process flat out reads 1.0. Click a column header to sort.",
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": ref, "expr": e, "instant": True, "format": "table", "datasource": DS}
                    for ref, e in queries],
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "job": True, "instance": True},
                "indexByName": {"groupname": 0, "Value #cpu": 1, "Value #rss": 2, "Value #threads": 3,
                                "Value #procs": 4, "Value #age": 5},
                "renameByName": names}},
        ],
        "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
            col("CPU (cores)", "short", 2), col("RAM (RSS)", "bytes", 1), col("Threads", "short", 0),
            col("Processes", "short", 0), col("Running for", "s", 0),
            {"matcher": {"id": "byName", "options": "CPU (cores)"},
             "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                            {"id": "color", "value": {"mode": "thresholds"}},
                            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                {"color": "transparent", "value": None}, {"color": "green", "value": 0.5},
                                {"color": "orange", "value": 8}]}}]},
        ]},
        "options": {"showHeader": True, "sortBy": [{"displayName": "CPU (cores)", "desc": True}],
                    "cellHeight": "sm", "footer": {"show": False}},
    })


# ── At a glance ──────────────────────────────────────────────────────────────
row("At a glance", 0)
stat("State", f'{BUSY} > bool {IDLE_BELOW}', 0, 1, mappings=[IDLEBUSY],
     steps=[{"color": "blue", "value": None}, {"color": "green", "value": 1}],
     desc=f"BUSY when the box uses {IDLE_BELOW} cores or more in total (idle background is about 0.03). One "
          "single-threaded process is about 1 core, so it counts as busy.")
stat("Busy cores", BUSY, 3, 1, decimals=2, graph=True,
     steps=[{"color": "blue", "value": None}, {"color": "green", "value": IDLE_BELOW}],
     desc="Cores' worth of non-idle CPU time (iowait included: a job waiting on disk is still working), of 128.")
stat("Busiest process", f'topk(1, {PROC_CPU})', 6, 1, w=6, decimals=2, legend="{{groupname}}",
     text="value_and_name", steps=[{"color": "blue", "value": None}, {"color": "green", "value": IDLE_BELOW}],
     desc="The process group using the most CPU right now, in cores.")
stat("Exporters", f'sum(up{{job=~"ampere-node|ampere-process"}}) or vector(0)', 12, 1, unit="none",
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 1}, {"color": "green", "value": 2}],
     desc="How many of the two exporters (node :9100, process :9256) Prometheus can scrape. 2 is healthy.")
stat("Memory used", f'100 * ({USED}) / {TOTAL}', 15, 1, unit="percent", graph=True,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 75}, {"color": "red", "value": 90}],
     desc="Total minus MemAvailable: page cache (model files read from disk) is not counted.")
stat("Disk free", f'node_filesystem_avail_bytes{{{ROOT_FS}}}', 18, 1, unit="bytes", decimals=0,
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 100 * 1000**3},
            {"color": "green", "value": 200 * 1000**3}],
     desc="Free space on / (the NVMe), where models and run artifacts live.")
stat("Uptime", f'time() - node_boot_time_seconds{{{J}}}', 21, 1, unit="s",
     steps=[{"color": "orange", "value": None}, {"color": "green", "value": 3600}])

# ── Processes ────────────────────────────────────────────────────────────────
row("Processes", 5)
process_table(0, 6, 24, 10)
timeseries("Top 10 processes by CPU", [(f'topk(10, {PROC_CPU}) > 0.05', "{{groupname}}")], 0, 16, 12, 10,
           decimals=2, desc="Cores per process group. A flat line at 1.0 is a single-threaded process flat out.")
timeseries("Top 10 processes by RAM", [(f'topk(10, {PROC_RSS})', "{{groupname}}")], 12, 16, 12, 10,
           unit="bytes", desc="Resident memory per process group.")

# ── CPU ──────────────────────────────────────────────────────────────────────
row("CPU", 26)
timeseries("Busy cores by mode",
           [(f'sum by (mode) (rate(node_cpu_seconds_total{{{J}, mode!="idle"}}[$__rate_interval]))', "{{mode}}")],
           0, 27, 12, 8, stack=True, decimals=2)
timeseries("Load average",
           [(f'node_load1{{{J}}}', "1m"), (f'node_load5{{{J}}}', "5m"), (f'node_load15{{{J}}}', "15m")],
           12, 27, 12, 8, decimals=2,
           desc="Runnable plus uninterruptible tasks. A single-threaded job holds this near 1.")

# ── Memory, disk & network ───────────────────────────────────────────────────
row("Memory, disk & network", 35)
timeseries("Memory",
           [(USED, "used"),
            (f'node_memory_Cached_bytes{{{J}}} + node_memory_Buffers_bytes{{{J}}}', "page cache"),
            (TOTAL, "total")],
           0, 36, 8, 8, unit="bytes",
           overrides=[{"matcher": {"id": "byName", "options": "total"},
                       "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}},
                                      {"id": "custom.fillOpacity", "value": 0}]}])
timeseries("Disk throughput",
           [(f'rate(node_disk_read_bytes_total{{{J}, device=~"nvme.+n[0-9]+"}}[$__rate_interval])', "read {{device}}"),
            (f'-rate(node_disk_written_bytes_total{{{J}, device=~"nvme.+n[0-9]+"}}[$__rate_interval])',
             "write {{device}}")],
           8, 36, 8, 8, unit="Bps", min_=None)
timeseries("Network",
           [(f'rate(node_network_receive_bytes_total{{{NIC}}}[$__rate_interval]) > 0', "rx {{device}}"),
            (f'-rate(node_network_transmit_bytes_total{{{NIC}}}[$__rate_interval]) < 0', "tx {{device}}")],
           16, 36, 8, 8, unit="Bps", min_=None)

dashboard = {
    "uid": "ampere-altra",
    "title": "Ampere Altra (CPU box)",
    "tags": ["ampere", "cpu-box"],
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
# Ampere Altra dashboard: host metrics (job ampere-node) plus per-process CPU and RAM (job ampere-process).
# Provisioned by the Grafana sidecar (label grafana_dashboard); edit the generator, not the JSON:
# monitoring/dashboards/gen_ampere_node.py > monitoring/manifests/ampere-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ampere-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  ampere-altra.json: |
"""

body = json.dumps(dashboard, indent=1)
sys.stdout.write(HEADER + "".join("    " + line + "\n" for line in body.splitlines()))
