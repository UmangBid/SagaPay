"""Generate a static HTML executive report from Prometheus queries."""

import argparse
import html
import math
import os
from datetime import datetime, timedelta, timezone

import requests


def prom_query(prom_url: str, expr: str) -> float:
    """Execute an instant Prometheus query and return a numeric scalar."""

    resp = requests.get(
        f"{prom_url.rstrip('/')}/api/v1/query",
        params={"query": expr},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    result = payload.get("data", {}).get("result", [])
    if not result:
        return 0.0
    value = float(result[0]["value"][1])
    return value if math.isfinite(value) else 0.0


def prom_query_range(prom_url: str, expr: str, start_ts: int, end_ts: int, step: int) -> list[float]:
    """Execute range query and return numeric series for simple charting."""

    resp = requests.get(
        f"{prom_url.rstrip('/')}/api/v1/query_range",
        params={
            "query": expr,
            "start": start_ts,
            "end": end_ts,
            "step": step,
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    result = payload.get("data", {}).get("result", [])
    if not result:
        return []
    values = []
    for value in result[0]["values"]:
        parsed = float(value[1])
        values.append(parsed if math.isfinite(parsed) else 0.0)
    return values


def sparkline_svg(values: list[float], width: int = 360, height: int = 100) -> str:
    """Render a tiny inline SVG sparkline for one metric series."""

    clean_values = [v for v in values if math.isfinite(v)]
    if not clean_values:
        return f"<svg width='{width}' height='{height}'><text x='10' y='55' fill='#888'>no data</text></svg>"
    vmin = min(clean_values)
    vmax = max(clean_values)
    span = vmax - vmin if vmax != vmin else 1.0
    points = []
    for idx, value in enumerate(values):
        if not math.isfinite(value):
            value = vmin
        x = int((idx / max(1, len(values) - 1)) * (width - 10)) + 5
        y = int(height - 5 - ((value - vmin) / span) * (height - 10))
        points.append(f"{x},{y}")
    polyline = " ".join(points)
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        "style='background:#111827;border:1px solid #1f2937;border-radius:8px;'>"
        f"<polyline fill='none' stroke='#60a5fa' stroke-width='2' points='{polyline}' />"
        "</svg>"
    )


def card(title: str, value: str) -> str:
    """Render one KPI card block."""

    return (
        "<div style='background:#0f172a;padding:14px;border-radius:10px;border:1px solid #1e293b;'>"
        f"<div style='font-size:13px;color:#94a3b8'>{html.escape(title)}</div>"
        f"<div style='font-size:24px;margin-top:6px'>{html.escape(value)}</div>"
        "</div>"
    )


def chart_block(title: str, expr: str, values: list[float]) -> str:
    """Render one chart section with query text + sparkline."""

    latest = 0.0
    for value in reversed(values):
        if math.isfinite(value):
            latest = value
            break
    return (
        "<div style='background:#0b1220;padding:14px;border-radius:10px;border:1px solid #1e293b;'>"
        f"<div style='font-size:14px;font-weight:600;margin-bottom:8px'>{html.escape(title)}</div>"
        f"<div style='font-size:12px;color:#94a3b8;margin-bottom:10px'>latest: {latest:.4f}</div>"
        f"{sparkline_svg(values)}"
        f"<div style='font-size:11px;color:#64748b;margin-top:8px'>query: {html.escape(expr)}</div>"
        "</div>"
    )


def main() -> None:
    """CLI entrypoint for generating dashboard-like HTML output."""

    parser = argparse.ArgumentParser(description="Generate static executive HTML report from Prometheus metrics.")
    parser.add_argument("--prom-url", default="http://localhost:9090")
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--output", default="reports/executive_report.html")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.hours)
    start_ts = int(start.timestamp())
    end_ts = int(now.timestamp())

    summary_queries = {
        "API p95 latency (s)": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service='api-gateway'}[5m])) by (le))",
        "API request rate (req/s)": "sum(rate(http_requests_total{service='api-gateway'}[5m]))",
        "E2E saga p95 (s)": "histogram_quantile(0.95, sum(rate(payment_e2e_seconds_bucket{service='orchestrator'}[5m])) by (le))",
        "Kafka queue p95 (s)": "histogram_quantile(0.95, sum(rate(event_queue_delay_seconds_bucket[5m])) by (le))",
        "DLQ published (last 1h)": "sum(increase(dlq_published_total[1h]))",
        "Outbox pending (current)": "sum(outbox_pending_total)",
        "Retry count (last 1h)": "sum(increase(retries_total[1h]))",
        "Failure rate (%)": "100 * (sum(rate(http_requests_total{service='api-gateway',status_code=~'5..'}[5m])) / clamp_min(sum(rate(http_requests_total{service='api-gateway'}[5m])), 1e-9))",
    }

    chart_queries = {
        "API p95 latency (s)": summary_queries["API p95 latency (s)"],
        "API request rate (req/s)": summary_queries["API request rate (req/s)"],
        "E2E saga p95 (s)": summary_queries["E2E saga p95 (s)"],
        "Kafka queue p95 (s)": summary_queries["Kafka queue p95 (s)"],
        "Outbox pending": "sum(outbox_pending_total)",
        "DLQ published rate (5m)": "sum(rate(dlq_published_total[5m]))",
    }

    summary_values = {}
    for label, expr in summary_queries.items():
        try:
            summary_values[label] = prom_query(args.prom_url, expr)
        except Exception:
            summary_values[label] = 0.0

    chart_values = {}
    for label, expr in chart_queries.items():
        try:
            chart_values[label] = prom_query_range(args.prom_url, expr, start_ts, end_ts, args.step_seconds)
        except Exception:
            chart_values[label] = []

    cards_html = "".join(
        [
            card("API p95", f"{summary_values['API p95 latency (s)']:.3f} s"),
            card("API RPS", f"{summary_values['API request rate (req/s)']:.2f} req/s"),
            card("E2E p95", f"{summary_values['E2E saga p95 (s)']:.3f} s"),
            card("Queue p95", f"{summary_values['Kafka queue p95 (s)']:.3f} s"),
            card("DLQ (1h)", f"{summary_values['DLQ published (last 1h)']:.0f}"),
            card("Outbox pending", f"{summary_values['Outbox pending (current)']:.0f}"),
            card("Retries (1h)", f"{summary_values['Retry count (last 1h)']:.0f}"),
            card("Gateway 5xx rate", f"{summary_values['Failure rate (%)']:.2f}%"),
        ]
    )

    charts_html = "".join(
        [
            chart_block(title, chart_queries[title], chart_values[title])
            for title in [
                "API p95 latency (s)",
                "API request rate (req/s)",
                "E2E saga p95 (s)",
                "Kafka queue p95 (s)",
                "Outbox pending",
                "DLQ published rate (5m)",
            ]
        ]
    )

    rendered_at = now.strftime("%Y-%m-%d %H:%M:%SZ")
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SagaPay Executive Report</title>
</head>
<body style="margin:0;background:#020617;color:#e2e8f0;font-family:ui-sans-serif,Segoe UI,Roboto,Arial;">
  <div style="max-width:1200px;margin:24px auto;padding:0 16px;">
    <h1 style="margin:0 0 8px 0;">SagaPay Executive Report</h1>
    <div style="color:#94a3b8;font-size:13px;">Window: last {args.hours}h | Generated: {rendered_at}</div>
    <div style="margin-top:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;">
      {cards_html}
    </div>
    <h2 style="margin-top:26px;margin-bottom:10px;">Metric Trends</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px;">
      {charts_html}
    </div>
  </div>
</body>
</html>
"""

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fp:
        fp.write(html_doc)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
