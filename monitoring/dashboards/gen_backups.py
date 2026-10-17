"""Generate the Backups Grafana dashboard ConfigMap.

    python3 monitoring/dashboards/gen_backups.py > monitoring/manifests/backups-dashboard.yaml

Everything comes from kube-state-metrics: CronJob status for the latest runs, Job metrics (joined to their CronJob
through kube_job_owner) for history. Prometheus keeps 10 days; Kubernetes keeps the last 3 successful and 3 failed
Jobs per CronJob, which bounds the per-run table.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
NS = 'namespace=~"postgres|secrets-backup|offsite-backup"'
# A Job metric with its CronJob's name as label `cronjob`.
OWNED = ('label_replace({m}{{' + NS + '}} * on(namespace, job_name) group_left(owner_name) '
         'kube_job_owner{{' + NS + ', owner_kind="CronJob"}}, "cronjob", "$1", "owner_name", "(.*)")')
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


def color_cell(name, steps, mappings=None, unit=None):
    props = [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": steps}}]
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    if unit:
        props.append({"id": "unit", "value": unit})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def unit_of(name, unit):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "unit", "value": unit}]}


# ── Latest run per backup ────────────────────────────────────────────────────
row("Latest run per backup", 0)
latest = {
    "type": "table", "title": "Backups", "id": nid(), "datasource": DS,
    "description": "One row per backup CronJob. 'Failed Jobs kept' counts failed runs Kubernetes still keeps "
                   "(up to 3); it clears as newer runs replace them.",
    "gridPos": {"h": 11, "w": 24, "x": 0, "y": 1},
    "targets": [
        target("A", f'kube_cronjob_info{{{NS}}}'),
        target("B", f'kube_cronjob_status_last_successful_time{{{NS}}} * 1000'),
        target("C", f'kube_cronjob_status_last_schedule_time{{{NS}}} * 1000'),
        target("D", 'max by (namespace, cronjob) (' + OWNED.format(m="kube_job_status_completion_time")
               + ' - on(namespace, job_name, cronjob) ' + OWNED.format(m="kube_job_status_start_time")
               + ' and on(namespace, cronjob) (' + OWNED.format(m="kube_job_status_start_time")
               + ' == on(namespace, cronjob) group_left max by (namespace, cronjob) ('
               + OWNED.format(m="kube_job_status_start_time") + ')))'),
        target("E", 'sum by (namespace, cronjob) (' + OWNED.format(m="kube_job_status_failed") + ' > 0) or '
               f'0 * kube_cronjob_info{{{NS}}}'),
        target("F", f'kube_cronjob_status_active{{{NS}}}'),
        target("G", f'kube_cronjob_spec_suspend{{{NS}}}'),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {k: True for k in (
                "Time", "__name__", "container", "endpoint", "instance", "job", "pod", "service",
                "concurrency_policy", "Value #A")},
            "indexByName": {"namespace": 0, "cronjob": 1, "schedule": 2, "timezone": 3, "Value #B": 4,
                            "Value #C": 5, "Value #D": 6, "Value #E": 7, "Value #F": 8, "Value #G": 9},
            "renameByName": {"Value #B": "Last success", "Value #C": "Last started", "Value #D": "Last duration",
                             "Value #E": "Failed Jobs kept", "Value #F": "Running now",
                             "Value #G": "Suspended", "cronjob": "Backup"}}},
    ],
    "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
        unit_of("Last success", "dateTimeFromNow"),
        unit_of("Last started", "dateTimeFromNow"),
        unit_of("Last duration", "s"),
        color_cell("Failed Jobs kept", [{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        color_cell("Running now", [{"color": "transparent", "value": None}, {"color": "blue", "value": 1}],
                   mappings=[{"type": "value", "options": {"0": {"text": "-"}, "1": {"text": "running"}}}]),
        color_cell("Suspended", [{"color": "transparent", "value": None}, {"color": "orange", "value": 1}],
                   mappings=[{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "SUSPENDED"}}}]),
    ]},
    "options": {"showHeader": True, "cellHeight": "sm", "sortBy": [{"displayName": "Backup", "desc": False}]},
}
panels.append(latest)

# ── History (10 days of Prometheus data) ─────────────────────────────────────
row("History (last 10 days at most)", 12)
VALUE_MAP_RUN = [{"type": "value", "options": {"0": {"text": "idle", "color": "transparent"},
                                               "1": {"text": "running", "color": "blue"}}}]
panels.append({
    "type": "state-timeline", "title": "When each backup ran", "id": nid(), "datasource": DS,
    "description": "Blue while a backup Job is active; the bar's width is how long it ran.",
    "gridPos": {"h": 10, "w": 24, "x": 0, "y": 13},
    "targets": [target("A", 'max by (cronjob) (' + OWNED.format(m="kube_job_status_active") + ')',
                       instant=False, fmt=None, legend="{{cronjob}}")],
    "fieldConfig": {"defaults": {"mappings": VALUE_MAP_RUN, "color": {"mode": "thresholds"},
                                 "thresholds": {"mode": "absolute", "steps": [
                                     {"color": "transparent", "value": None}, {"color": "blue", "value": 1}]},
                                 "custom": {"fillOpacity": 80, "lineWidth": 0}}, "overrides": []},
    "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8, "alignValue": "left",
                "legend": {"showLegend": False}},
})
panels.append({
    "type": "state-timeline", "title": "Failures", "id": nid(), "datasource": DS,
    "description": "Red while a failed backup Job exists (Kubernetes keeps the last 3 failed per CronJob).",
    "gridPos": {"h": 8, "w": 24, "x": 0, "y": 23},
    "targets": [target("A", 'max by (cronjob) (' + OWNED.format(m="kube_job_status_failed") + ' > bool 0)'
                       f' or max by (cronjob) (0 * kube_cronjob_info{{{NS}}})',
                       instant=False, fmt=None, legend="{{cronjob}}")],
    "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {
        "0": {"text": "ok", "color": "green"}, "1": {"text": "failed run", "color": "red"}}}],
        "color": {"mode": "thresholds"},
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None},
                                                     {"color": "red", "value": 1}]},
        "custom": {"fillOpacity": 70, "lineWidth": 0}}, "overrides": []},
    "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8, "legend": {"showLegend": False}},
})

# ── Individual runs Kubernetes still keeps ───────────────────────────────────
row("Runs Kubernetes still keeps (last 3 successful + 3 failed per backup)", 31)
panels.append({
    "type": "table", "title": "Runs", "id": nid(), "datasource": DS,
    "gridPos": {"h": 14, "w": 24, "x": 0, "y": 32},
    "targets": [
        target("A", OWNED.format(m="kube_job_status_start_time") + ' * 1000'),
        target("B", OWNED.format(m="kube_job_status_completion_time") + ' * 1000'),
        target("C", OWNED.format(m="kube_job_status_completion_time") + ' - on(namespace, job_name, cronjob) '
               + OWNED.format(m="kube_job_status_start_time")),
        target("D", OWNED.format(m="kube_job_status_succeeded") + ' - on(namespace, job_name, cronjob) '
               + OWNED.format(m="kube_job_status_failed") + ' * 2 + on(namespace, job_name, cronjob) '
               + OWNED.format(m="kube_job_status_active") + ' * 3'),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {k: True for k in (
                "Time", "__name__", "container", "endpoint", "instance", "job", "pod", "service",
                "owner_is_controller", "owner_kind", "owner_name")},
            "indexByName": {"cronjob": 0, "job_name": 1, "Value #A": 2, "Value #B": 3, "Value #C": 4,
                            "Value #D": 5, "namespace": 6},
            "renameByName": {"cronjob": "Backup", "job_name": "Run", "Value #A": "Started",
                             "Value #B": "Finished", "Value #C": "Duration", "Value #D": "Result"}}},
    ],
    "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
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

dash = {
    "uid": "backups", "title": "Backups", "tags": ["backups", "overview"],
    "timezone": "browser", "schemaVersion": 39, "refresh": "1m", "editable": False,
    "time": {"from": "now-7d", "to": "now"},
    "templating": {"list": [{"type": "datasource", "name": "datasource", "label": "Prometheus",
                             "query": "prometheus", "current": {}, "hide": 0}]},
    "annotations": {"list": []},
    "links": [{"title": "System Health", "type": "link", "url": "/d/system-health"}],
    "panels": panels,
}

body = json.dumps(dash, indent=1)
sys.stdout.write("""# Backups dashboard: latest run per backup CronJob, when each ran, failures, and the runs Kubernetes still keeps.
# Provisioned by the Grafana sidecar (label grafana_dashboard). Edit the generator, not the JSON:
# python3 monitoring/dashboards/gen_backups.py > monitoring/manifests/backups-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: backups-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  backups.json: |
""" + "\n".join("    " + line for line in body.splitlines()) + "\n")
