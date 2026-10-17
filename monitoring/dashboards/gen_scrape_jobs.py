"""Generate the Scrape Jobs Grafana dashboard ConfigMap.

    python3 monitoring/dashboards/gen_scrape_jobs.py > monitoring/manifests/scrape-jobs-dashboard.yaml

Job state comes from scrape-job-manager's own metrics (scrape_job_*; the job's namespace is `exported_namespace`).
Run history comes from kube-state-metrics Job metrics, joined to their ScrapeJob through kube_job_owner. Prometheus
keeps 10 days; scrape-job-manager prunes old Jobs, which bounds the per-run table.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
SJ = 'exported_namespace=~"$namespace", scrape_job=~"$job"'
# A Job metric with its ScrapeJob's name as label `scrape_job`, for the selected namespaces/jobs.
OWNED = ('label_replace({m}{{namespace=~"$namespace"}} * on(namespace, job_name) group_left(owner_name) '
         'kube_job_owner{{namespace=~"$namespace", owner_kind="ScrapeJob", owner_name=~"$job"}}, '
         '"scrape_job", "$1", "owner_name", "(.*)")')
panels = []


def nid():
    return len(panels) + 1


def target(ref, expr, instant=True, fmt="table", legend=None):
    t = {"refId": ref, "expr": expr, "datasource": DS}
    if instant:
        t["instant"] = True
    else:
        t["range"] = True
    if fmt:
        t["format"] = fmt
    if legend:
        t["legendFormat"] = legend
    return t


def row(title, y):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}})


def stat(title, expr, x, y, color, w=4, h=4, desc="", unit="none", steps=None):
    steps = steps or [{"color": color, "value": None}]
    panels.append({
        "type": "stat", "title": title, "id": nid(), "datasource": DS, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target("A", expr, fmt=None)],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 0, "color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "none", "textMode": "value",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })


def unit_of(name, unit):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "unit", "value": unit}]}


def color_cell(name, steps, mappings=None):
    props = [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": steps}}]
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


HIDE = ("Time", "__name__", "container", "endpoint", "instance", "job", "pod", "service", "namespace",
        "owner_is_controller", "owner_kind", "owner_name")

# ── At a glance ──────────────────────────────────────────────────────────────
row("At a glance", 0)
for i, (phase, color) in enumerate([("Healthy", "green"), ("Degraded", "orange"), ("Disabled", "text")]):
    stat(phase, f'count(scrape_job_phase{{{SJ}, phase="{phase}"}} == 1) or vector(0)', i * 4, 1, color)
stat("Stale", f'count(scrape_job_stale{{{SJ}}} == 1) or vector(0)', 12, 1, "green",
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
     desc="Jobs whose last success is older than their schedule allows.")
stat("Running now", 'count(' + OWNED.format(m="kube_job_status_active") + ' > 0) or vector(0)', 16, 1, "blue")
stat("Operator last tick", 'time() - max(scrape_operator_last_tick_timestamp_seconds)', 20, 1, "green",
     unit="s", steps=[{"color": "green", "value": None}, {"color": "orange", "value": 120},
                      {"color": "red", "value": 600}],
     desc="Seconds since scrape-job-manager's reconcile loop last ran.")

# ── Jobs ─────────────────────────────────────────────────────────────────────
row("Jobs", 5)
panels.append({
    "type": "table", "title": "Jobs", "id": nid(), "datasource": DS,
    "description": "Items: rows the last successful run reported; baseline: what scrape-job-manager expects "
                   "(a large drop below it degrades the job).",
    "gridPos": {"h": 16, "w": 24, "x": 0, "y": 6},
    "targets": [
        target("A", f'scrape_job_phase{{{SJ}}} == 1'),
        target("B", f'scrape_job_last_success_timestamp_seconds{{{SJ}}} * 1000'),
        target("C", f'scrape_job_consecutive_failures{{{SJ}}}'),
        target("D", f'scrape_job_last_items{{{SJ}}}'),
        target("E", f'scrape_job_baseline_items{{{SJ}}}'),
        target("F", f'scrape_job_last_duration_seconds{{{SJ}}}'),
        target("G", f'scrape_job_stale{{{SJ}}}'),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {k: True for k in (*HIDE, "Value #A")},
            "indexByName": {"exported_namespace": 0, "scrape_job": 1, "scraper": 2, "phase": 3, "Value #B": 4,
                            "Value #C": 5, "Value #D": 6, "Value #E": 7, "Value #F": 8, "Value #G": 9},
            "renameByName": {"exported_namespace": "Namespace", "scrape_job": "Job", "scraper": "Scraper",
                             "phase": "Phase", "Value #B": "Last success", "Value #C": "Failures in a row",
                             "Value #D": "Items", "Value #E": "Baseline", "Value #F": "Last duration",
                             "Value #G": "Stale"}}},
    ],
    "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True}}, "overrides": [
        unit_of("Last success", "dateTimeFromNow"),
        unit_of("Last duration", "s"),
        color_cell("Phase", [{"color": "transparent", "value": None}], mappings=[{"type": "value", "options": {
            "Healthy": {"color": "green"}, "Degraded": {"color": "orange"}, "Disabled": {"color": "text"},
            "Pending": {"color": "blue"}}}]),
        color_cell("Failures in a row", [{"color": "transparent", "value": None}, {"color": "orange", "value": 1},
                                         {"color": "red", "value": 3}]),
        color_cell("Stale", [{"color": "transparent", "value": None}, {"color": "orange", "value": 1}],
                   mappings=[{"type": "value", "options": {"0": {"text": "-"}, "1": {"text": "STALE"}}}]),
    ]},
    "options": {"showHeader": True, "cellHeight": "sm",
                "sortBy": [{"displayName": "Failures in a row", "desc": True}]},
})

# ── History ──────────────────────────────────────────────────────────────────
row("History (last 10 days at most)", 22)
panels.append({
    "type": "state-timeline", "title": "When each job ran", "id": nid(), "datasource": DS,
    "description": "Blue while a run's Job is active (retries included). Filter with the variables at the top "
                   "when the list is long.",
    "gridPos": {"h": 18, "w": 24, "x": 0, "y": 23},
    "targets": [target("A", 'max by (namespace, scrape_job) (' + OWNED.format(m="kube_job_status_active")
                       + ' > bool 0)', instant=False, fmt=None, legend="{{namespace}}/{{scrape_job}}")],
    "fieldConfig": {"defaults": {
        "mappings": [{"type": "value", "options": {"0": {"text": "idle", "color": "transparent"},
                                                   "1": {"text": "running", "color": "blue"}}}],
        "color": {"mode": "thresholds"},
        "thresholds": {"mode": "absolute", "steps": [{"color": "transparent", "value": None},
                                                     {"color": "blue", "value": 1}]},
        "custom": {"fillOpacity": 80, "lineWidth": 0}}, "overrides": []},
    "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8, "legend": {"showLegend": False}},
})
panels.append({
    "type": "timeseries", "title": "Failures in a row", "id": nid(), "datasource": DS,
    "gridPos": {"h": 9, "w": 12, "x": 0, "y": 41},
    "targets": [target("A", f'scrape_job_consecutive_failures{{{SJ}}} > 0', instant=False, fmt=None,
                       legend="{{exported_namespace}}/{{scrape_job}}")],
    "fieldConfig": {"defaults": {"min": 0, "decimals": 0, "custom": {"drawStyle": "line", "lineInterpolation":
                                                                      "stepAfter", "lineWidth": 2}},
                    "overrides": []},
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
})
panels.append({
    "type": "timeseries", "title": "Items per successful run", "id": nid(), "datasource": DS,
    "gridPos": {"h": 9, "w": 12, "x": 12, "y": 41},
    "targets": [target("A", f'scrape_job_last_items{{{SJ}}}', instant=False, fmt=None,
                       legend="{{exported_namespace}}/{{scrape_job}}")],
    "fieldConfig": {"defaults": {"min": 0, "decimals": 0, "custom": {"drawStyle": "line", "lineInterpolation":
                                                                      "stepAfter", "lineWidth": 1}},
                    "overrides": []},
    "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"]},
                "tooltip": {"mode": "multi", "sort": "desc"}},
})

# ── Runs ─────────────────────────────────────────────────────────────────────
row("Runs Kubernetes still keeps", 50)
panels.append({
    "type": "table", "title": "Runs", "id": nid(), "datasource": DS,
    "description": "One row per attempt (a run's retries are separate Jobs: <job>-<run>-<attempt>).",
    "gridPos": {"h": 14, "w": 24, "x": 0, "y": 51},
    "targets": [
        target("A", OWNED.format(m="kube_job_status_start_time") + ' * 1000'),
        target("B", OWNED.format(m="kube_job_status_completion_time") + ' * 1000'),
        target("C", OWNED.format(m="kube_job_status_completion_time") + ' - on(namespace, job_name, scrape_job) '
               + OWNED.format(m="kube_job_status_start_time")),
        target("D", OWNED.format(m="kube_job_status_succeeded") + ' - on(namespace, job_name, scrape_job) '
               + 'sum by (namespace, job_name, scrape_job) (' + OWNED.format(m="kube_job_status_failed") + ') * 2 + on(namespace, job_name, scrape_job) '
               + OWNED.format(m="kube_job_status_active") + ' * 3'),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {k: True for k in HIDE if k != "namespace"},
            "indexByName": {"namespace": 0, "scrape_job": 1, "job_name": 2, "Value #A": 3, "Value #B": 4,
                            "Value #C": 5, "Value #D": 6},
            "renameByName": {"namespace": "Namespace", "scrape_job": "Job", "job_name": "Attempt",
                             "Value #A": "Started", "Value #B": "Finished", "Value #C": "Duration",
                             "Value #D": "Result"}}},
    ],
    "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True}}, "overrides": [
        unit_of("Started", "dateTimeAsLocal"),
        unit_of("Finished", "dateTimeAsLocal"),
        unit_of("Duration", "s"),
        color_cell("Result", [{"color": "red", "value": None}, {"color": "green", "value": 1},
                              {"color": "blue", "value": 3}],
                   mappings=[{"type": "value", "options": {
                       "1": {"text": "succeeded", "color": "green"},
                       "-2": {"text": "failed", "color": "red"},
                       "3": {"text": "running", "color": "blue"}}}]),
    ]},
    "options": {"showHeader": True, "cellHeight": "sm", "sortBy": [{"displayName": "Started", "desc": True}]},
})


# ── Logs ─────────────────────────────────────────────────────────────────────
row("Logs (scraper container, via Loki)", 65)
panels.append({
    "type": "logs", "title": "Scraper logs", "id": nid(),
    "datasource": {"type": "loki", "uid": "loki"},
    "description": "Shipped by the otel-agent DaemonSet (docs/logging.md). Narrow with the Namespace/Job variables; "
                   "each line carries scrape_run and scrape_attempt for a single run.",
    "gridPos": {"h": 20, "w": 24, "x": 0, "y": 66},
    "targets": [{"refId": "A", "datasource": {"type": "loki", "uid": "loki"},
                 # k8s_container_name is the non-empty matcher LogQL requires when the variables are "All" (.*).
                 "expr": '{k8s_container_name="scraper", k8s_namespace_name=~"$namespace", service_name=~"$job"}'}],
    "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                "dedupStrategy": "none", "prettifyLogMessage": False},
})


def var(name, label, query):
    return {"type": "query", "name": name, "label": label, "datasource": DS,
            "query": {"query": query, "refId": f"{name}-var"}, "definition": query,
            "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"},
            "refresh": 2, "sort": 1, "hide": 0}


dash = {
    "uid": "scrape-jobs", "title": "Scrape Jobs", "tags": ["scrapers", "overview"],
    "timezone": "browser", "schemaVersion": 39, "refresh": "1m", "editable": False,
    "time": {"from": "now-2d", "to": "now"},
    "templating": {"list": [
        {"type": "datasource", "name": "datasource", "label": "Prometheus", "query": "prometheus",
         "current": {}, "hide": 0},
        var("namespace", "Namespace", "label_values(scrape_job_phase, exported_namespace)"),
        var("job", "Job", 'label_values(scrape_job_phase{exported_namespace=~"$namespace"}, scrape_job)'),
    ]},
    "annotations": {"list": []},
    "links": [{"title": "System Health", "type": "link", "url": "/d/system-health"},
              {"title": "scrape-job-manager UI", "type": "link", "url": "https://sjm.danwils.com",
               "targetBlank": True}],
    "panels": panels,
}

body = json.dumps(dash, indent=1)
sys.stdout.write("""# Scrape Jobs dashboard: every scrape-job-manager job's state, run history and kept runs, filterable by namespace/job.
# Provisioned by the Grafana sidecar (label grafana_dashboard). Edit the generator, not the JSON:
# python3 monitoring/dashboards/gen_scrape_jobs.py > monitoring/manifests/scrape-jobs-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scrape-jobs-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  scrape-jobs.json: |
""" + "\n".join("    " + line for line in body.splitlines()) + "\n")
