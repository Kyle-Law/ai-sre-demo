"""Grafana client (Viewer service-account token): PromQL via the datasource
proxy, and Grafana-managed alert state for verification."""

from __future__ import annotations

import json
import time

import requests


class Grafana:
    def __init__(self, url: str, token: str, prom_uid: str):
        self.url = url
        self.prom_uid = prom_uid
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self.session.get(f"{self.url}{path}", params=params, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Grafana GET {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def promql(self, query: str, range_minutes: int | None = None) -> dict:
        base = f"/api/datasources/proxy/uid/{self.prom_uid}/api/v1"
        if range_minutes:
            end = time.time()
            start = end - range_minutes * 60
            step = max(15, int(range_minutes * 60 / 60))
            return self._get(f"{base}/query_range", {"query": query, "start": start, "end": end, "step": step})
        return self._get(f"{base}/query", {"query": query})

    def active_alerts(self) -> list[dict]:
        """Grafana-managed alert instances currently pending or firing."""
        data = self._get("/api/prometheus/grafana/api/v1/alerts")
        alerts = data.get("data", {}).get("alerts", [])
        # Only pending/firing instances count; ignore Normal / NoData / inactive entries.
        return [a for a in alerts
                if str(a.get("state", "")).lower().split(" ")[0] in {"alerting", "firing", "pending"}]

    def active_alerts_for(self, namespace: str, workload: str) -> list[dict]:
        return [
            a for a in self.active_alerts()
            if a.get("labels", {}).get("namespace") == namespace
            and a.get("labels", {}).get("workload") == workload
            and a.get("labels", {}).get("ai_triage") == "true"
        ]


def summarize_prom(result: dict, max_series: int = 20) -> str:
    """Compact, model-friendly rendering of a Prometheus API response."""
    if result.get("status") != "success":
        return json.dumps(result)[:2000]
    data = result.get("data", {})
    series = data.get("result", [])
    lines = [f"resultType={data.get('resultType')} series={len(series)}"]
    for s in series[:max_series]:
        metric = s.get("metric", {})
        if "values" in s:
            vals = s["values"]
            pts = ", ".join(v for _, v in vals[-8:])
            lines.append(f"{metric} last {min(8, len(vals))} of {len(vals)} points: [{pts}]")
        else:
            lines.append(f"{metric} = {s.get('value', [None, None])[1]}")
    if len(series) > max_series:
        lines.append(f"... {len(series) - max_series} more series")
    return "\n".join(lines)
