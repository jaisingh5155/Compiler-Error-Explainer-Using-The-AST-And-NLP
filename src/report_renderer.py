"""
src/report_renderer.py
──────────────────────
Report renderer for batch evaluation results.

Supports:
- Self-contained, zero-external-dependency HTML reports with embedded CSS & JS:
  - Header with summary KPI cards (healed, gave_up, not_applicable, crashed, success rate, time).
  - Breakdown widgets for Patches by Safety Tier, Gate Failures, and Security CWEs.
  - Interactive table:
    - Real-time text search filter (matches filename, error categories, CWEs).
    - Status pill filter buttons (All, Healed, Gave Up, Not Applicable, Crashed).
    - Click-to-sort columns (File, Status, Errors Before/After, Duration).
    - Per-file expandable Agent Execution Trace rendered via trace_view.format_trace_html.
- Standalone JSON reports.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Dict, List, Union

from batch_runner import BatchResult
from trace_view import format_trace_html


def _extract_trace_body(raw_trace_html: str) -> str:
    """Extract inner trace div from full HTML document for seamless inline embedding."""
    if not raw_trace_html:
        return "<div style='color: #64748b; font-style: italic;'>No trace steps recorded.</div>"
    match = re.search(r"<div class='agent-trace'[^>]*>(.*?)</div>\s*</body>", raw_trace_html, re.DOTALL)
    if match:
        return f"<div class='agent-trace' style='line-height: 1.5; font-size: 12px;'>{match.group(1)}</div>"
    return raw_trace_html


def render_html_report(batch_result: Union[BatchResult, Dict[str, Any]]) -> str:
    """Render a fully self-contained HTML report with interactive sorting, filtering, and traces."""
    data = batch_result.to_dict() if hasattr(batch_result, "to_dict") else batch_result
    summary = data.get("summary", {})
    files = data.get("files", [])
    timestamp = data.get("timestamp", "")

    total = summary.get("total_files", len(files))
    healed = summary.get("healed", 0)
    gave_up = summary.get("gave_up", 0)
    na = summary.get("not_applicable", 0)
    crashed = summary.get("crashed", 0)
    attempted = summary.get("attempted", healed + gave_up)
    success_rate = summary.get("heal_success_percent", "0.0%")
    total_time = summary.get("total_time", 0.0)
    apply_mode = summary.get("apply", False)

    tiers = summary.get("patches_by_safety_tier", {})
    gate_failures = summary.get("gate_failure_breakdown", {})
    cwes = summary.get("security_findings_by_cwe", {})

    # Generate tier chips
    tier_chips = "".join(
        f"<span class='chip tier-chip'><strong>{html.escape(str(k))}:</strong> {v}</span>"
        for k, v in sorted(tiers.items())
    ) or "<span class='chip'>None</span>"

    # Generate gate failure chips
    gate_chips = "".join(
        f"<span class='chip gate-chip'><strong>{html.escape(str(k))}:</strong> {v}</span>"
        for k, v in sorted(gate_failures.items())
    ) or "<span class='chip'>None</span>"

    # Generate CWE chips
    cwe_chips = "".join(
        f"<span class='chip cwe-chip'><strong>{html.escape(str(k))}:</strong> {v}</span>"
        for k, v in sorted(cwes.items())
    ) or "<span class='chip'>None</span>"

    # Generate table rows
    table_rows = []
    for idx, f in enumerate(files, start=1):
        rel_path = f.get("rel_path", f.get("filepath", "unknown"))
        outcome = f.get("outcome", "not_applicable")
        duration = f.get("duration", 0.0)
        err_before = f.get("error_count_before", 0)
        err_after = f.get("error_count_after", 0)
        warn_before = f.get("warning_count_before", 0)
        warn_after = f.get("warning_count_after", 0)
        diags = f.get("diagnostics", [])
        sec_findings = f.get("security_findings", [])
        patches_applied = f.get("patches_applied", [])
        patches_blocked = f.get("patches_blocked", [])
        trace_log = f.get("trace_log", [])
        err_msg = f.get("error_message")

        badge_cls = {
            "healed": "badge-healed",
            "gave_up": "badge-gaveup",
            "not_applicable": "badge-na",
            "crashed": "badge-crashed",
        }.get(outcome, "badge-na")

        outcome_label = {
            "healed": "HEALED",
            "gave_up": "GAVE UP",
            "not_applicable": "NOT APPLICABLE",
            "crashed": "CRASHED",
        }.get(outcome, outcome.upper())

        # Categories list
        categories = sorted(set(d.get("category", "other") for d in diags if d.get("category")))
        cat_str = ", ".join(categories) if categories else "—"

        # CWEs list
        cwe_list = sorted(set(sf.get("cwe") for sf in sec_findings if sf.get("cwe")))
        cwe_str = ", ".join(cwe_list) if cwe_list else "—"

        # Patches info
        n_patches = len(patches_applied)
        n_blocked = len(patches_blocked)
        patch_info = f"{n_patches} applied"
        if n_blocked:
            patch_info += f" ({n_blocked} blocked)"

        # Expandable trace
        trace_inner = _extract_trace_body(format_trace_html(trace_log))
        if err_msg:
            trace_inner = f"<div class='crash-box'><strong>Crash Error:</strong><pre>{html.escape(err_msg)}</pre></div>" + trace_inner

        trace_expand = f"""
        <details class='trace-container'>
            <summary class='trace-toggle'>View Trace ({len(trace_log)} steps)</summary>
            <div class='trace-drawer'>
                {trace_inner}
            </div>
        </details>
        """

        search_corpus = f"{rel_path} {outcome} {cat_str} {cwe_str}".lower()

        table_rows.append(f"""
        <tr class='file-row' data-outcome='{outcome}' data-search='{html.escape(search_corpus)}'>
            <td class='col-num'>{idx}</td>
            <td class='col-file'>
                <div class='file-name'>{html.escape(rel_path)}</div>
                <div class='file-meta'>Category: {html.escape(cat_str)}</div>
            </td>
            <td class='col-status'>
                <span class='badge {badge_cls}'>{outcome_label}</span>
            </td>
            <td class='col-counts'>
                <div class='counts-pair'>
                    <span class='count-before'>{err_before} err / {warn_before} warn</span>
                    <span class='count-arrow'>&rarr;</span>
                    <span class='count-after { "count-clean" if err_after == 0 else "count-err" }'>{err_after} err / {warn_after} warn</span>
                </div>
            </td>
            <td class='col-patches'>{html.escape(patch_info)}</td>
            <td class='col-sec'>{html.escape(cwe_str)}</td>
            <td class='col-dur' data-val='{duration}'>{duration:.2f}s</td>
            <td class='col-trace'>{trace_expand}</td>
        </tr>
        """)

    rows_html = "\n".join(table_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>C++ Healer Batch Evaluation Report</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #283548;
            --border: #334155;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --green: #10b981;
            --green-bg: rgba(16, 185, 129, 0.15);
            --amber: #f59e0b;
            --amber-bg: rgba(245, 158, 11, 0.15);
            --red: #ef4444;
            --red-bg: rgba(239, 68, 68, 0.15);
            --blue: #3b82f6;
            --blue-bg: rgba(59, 130, 246, 0.15);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{ max-width: 1380px; margin: 0 auto; }}
        
        /* Header */
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 18px;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .report-title {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; }}
        .report-meta {{ font-size: 12px; color: var(--text-dim); text-align: right; }}

        /* Cards Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            position: relative;
            overflow: hidden;
        }}
        .kpi-card::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
        }}
        .kpi-card.healed::before {{ background: var(--green); }}
        .kpi-card.gave_up::before {{ background: var(--amber); }}
        .kpi-card.na::before {{ background: var(--blue); }}
        .kpi-card.crashed::before {{ background: var(--red); }}
        .kpi-card.total::before {{ background: var(--accent); }}

        .kpi-label {{ font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--text-dim); }}
        .kpi-value {{ font-size: 28px; font-weight: 800; margin-top: 4px; }}
        .kpi-subtext {{ font-size: 12px; color: var(--text-dim); margin-top: 2px; }}

        /* Breakdowns */
        .breakdowns-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .breakdown-box {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
        }}
        .breakdown-title {{ font-size: 13px; font-weight: 700; margin-bottom: 10px; color: var(--text-dim); text-transform: uppercase; }}
        .chip-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .chip {{
            background: #090d16;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 11px;
            color: var(--text-main);
        }}
        .tier-chip {{ border-left: 3px solid var(--accent); }}
        .gate-chip {{ border-left: 3px solid var(--amber); }}
        .cwe-chip {{ border-left: 3px solid var(--red); }}

        /* Toolbar */
        .toolbar {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .filter-group {{ display: flex; gap: 6px; flex-wrap: wrap; }}
        .filter-btn {{
            background: transparent;
            color: var(--text-dim);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .filter-btn:hover {{ background: var(--surface-hover); color: var(--text-main); }}
        .filter-btn.active {{
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }}
        .search-box {{
            background: #090d16;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 6px 12px;
            color: white;
            font-size: 13px;
            width: 280px;
            outline: none;
        }}
        .search-box:focus {{ border-color: var(--accent); }}

        /* Table */
        .table-wrap {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        th {{
            background: #151f30;
            color: var(--text-dim);
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{ color: var(--text-main); }}
        td {{
            padding: 12px 16px;
            border-bottom: 1px solid #1a2536;
            vertical-align: top;
        }}
        tr:hover td {{ background: var(--surface-hover); }}
        .col-num {{ color: var(--text-dim); width: 40px; }}
        .col-file {{ min-width: 240px; }}
        .file-name {{ font-weight: 600; color: #e2e8f0; font-family: monospace; font-size: 12px; }}
        .file-meta {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; }}
        .col-status {{ width: 140px; }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .badge-healed {{ background: var(--green-bg); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.3); }}
        .badge-gaveup {{ background: var(--amber-bg); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.3); }}
        .badge-na {{ background: var(--blue-bg); color: var(--blue); border: 1px solid rgba(59, 130, 246, 0.3); }}
        .badge-crashed {{ background: var(--red-bg); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3); }}

        .counts-pair {{ font-family: monospace; font-size: 11px; }}
        .count-before {{ color: #cbd5e1; }}
        .count-arrow {{ color: var(--text-dim); margin: 0 4px; }}
        .count-clean {{ color: var(--green); font-weight: bold; }}
        .count-err {{ color: var(--amber); }}
        
        .col-dur {{ font-family: monospace; color: var(--text-dim); font-size: 11px; }}

        /* Trace Container */
        .trace-container {{ margin-top: 4px; }}
        .trace-toggle {{
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
            color: var(--accent);
            outline: none;
        }}
        .trace-toggle:hover {{ text-decoration: underline; }}
        .trace-drawer {{
            margin-top: 8px;
            padding: 10px;
            background: #ffffff;
            color: #1e293b;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid var(--border);
        }}
        .crash-box {{
            background: #fef2f2;
            border: 1px solid #dc2626;
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
            color: #991b1b;
            font-size: 11px;
        }}
        .crash-box pre {{
            white-space: pre-wrap;
            font-family: monospace;
            margin-top: 4px;
        }}

        .gate-box {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; margin-top: 6px; background: #f8fafc; }}
        .gate-item {{ margin: 3px 0; font-size: 11px; }}
        .gate-badge {{ display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }}
        .badge-pass {{ background: #dcfce7; color: #15803d; }}
        .badge-fail {{ background: #fee2e2; color: #b91c1c; }}
    </style>
</head>
<body>
    <div class="container">
        <header class="report-header">
            <div>
                <h1 class="report-title">C++ Healer Batch Report</h1>
                <div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">
                    Mode: { "Live Writeback (--apply)" if apply_mode else "Safe Simulation (Read-Only)" }
                </div>
            </div>
            <div class="report-meta">
                <div><strong>Timestamp:</strong> {html.escape(timestamp)}</div>
                <div><strong>Total Time:</strong> {total_time:.2f}s</div>
            </div>
        </header>

        <!-- KPI Grid -->
        <section class="kpi-grid">
            <div class="kpi-card total">
                <div class="kpi-label">Total Files</div>
                <div class="kpi-value">{total}</div>
                <div class="kpi-subtext">{attempted} attempted repairs</div>
            </div>
            <div class="kpi-card healed">
                <div class="kpi-label">Healed (Clean)</div>
                <div class="kpi-value" style="color: var(--green);">{healed}</div>
                <div class="kpi-subtext">{success_rate} of attempted</div>
            </div>
            <div class="kpi-card gave_up">
                <div class="kpi-label">Gave Up</div>
                <div class="kpi-value" style="color: var(--amber);">{gave_up}</div>
                <div class="kpi-subtext">Safe stops / no fix found</div>
            </div>
            <div class="kpi-card na">
                <div class="kpi-label">Not Applicable</div>
                <div class="kpi-value" style="color: var(--blue);">{na}</div>
                <div class="kpi-subtext">Already clean / 0 errors</div>
            </div>
            <div class="kpi-card crashed">
                <div class="kpi-label">Crashed</div>
                <div class="kpi-value" style="color: { 'var(--red)' if crashed > 0 else 'var(--text-dim)' };">{crashed}</div>
                <div class="kpi-subtext">Unhandled exceptions / timeouts</div>
            </div>
        </section>

        <!-- Breakdown Panels -->
        <section class="breakdowns-grid">
            <div class="breakdown-box">
                <div class="breakdown-title">Patches by Safety Tier</div>
                <div class="chip-list">{tier_chips}</div>
            </div>
            <div class="breakdown-box">
                <div class="breakdown-title">Gate Failure Breakdown</div>
                <div class="chip-list">{gate_chips}</div>
            </div>
            <div class="breakdown-box">
                <div class="breakdown-title">Security Findings by CWE</div>
                <div class="chip-list">{cwe_chips}</div>
            </div>
        </section>

        <!-- Toolbar -->
        <section class="toolbar">
            <div class="filter-group">
                <button class="filter-btn active" onclick="setFilter('all', this)">All ({total})</button>
                <button class="filter-btn" onclick="setFilter('healed', this)">Healed ({healed})</button>
                <button class="filter-btn" onclick="setFilter('gave_up', this)">Gave Up ({gave_up})</button>
                <button class="filter-btn" onclick="setFilter('not_applicable', this)">N/A ({na})</button>
                <button class="filter-btn" onclick="setFilter('crashed', this)">Crashed ({crashed})</button>
            </div>
            <input type="text" id="searchInput" class="search-box" placeholder="Search file, category, CWE..." onkeyup="filterRows()"/>
        </section>

        <!-- Table -->
        <div class="table-wrap">
            <table id="batchTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">#</th>
                        <th onclick="sortTable(1)">File</th>
                        <th onclick="sortTable(2)">Outcome</th>
                        <th onclick="sortTable(3)">Before &rarr; After</th>
                        <th>Patches</th>
                        <th>Security / CWE</th>
                        <th onclick="sortTable(6)">Duration</th>
                        <th>Execution Trace</th>
                    </tr>
                </thead>
                <tbody id="tableBody">
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(status, btn) {{
            currentFilter = status;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            filterRows();
        }}

        function filterRows() {{
            const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
            const rows = document.querySelectorAll('#tableBody tr');
            rows.forEach(row => {{
                const outcome = row.getAttribute('data-outcome');
                const corpus = row.getAttribute('data-search') || '';
                const matchStatus = (currentFilter === 'all') || (outcome === currentFilter);
                const matchQuery = !query || corpus.includes(query);
                row.style.display = (matchStatus && matchQuery) ? '' : 'none';
            }});
        }}

        function sortTable(colIndex) {{
            const table = document.getElementById('batchTable');
            const tbody = document.getElementById('tableBody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const isAsc = table.getAttribute('data-sort-col') == colIndex && table.getAttribute('data-sort-dir') === 'asc';

            rows.sort((a, b) => {{
                let valA, valB;
                if (colIndex === 6) {{
                    valA = parseFloat(a.children[colIndex].getAttribute('data-val') || '0');
                    valB = parseFloat(b.children[colIndex].getAttribute('data-val') || '0');
                    return isAsc ? valB - valA : valA - valB;
                }}
                valA = a.children[colIndex].innerText.trim().toLowerCase();
                valB = b.children[colIndex].innerText.trim().toLowerCase();
                return isAsc ? valB.localeCompare(valA) : valA.localeCompare(valB);
            }});

            table.setAttribute('data-sort-col', colIndex);
            table.setAttribute('data-sort-dir', isAsc ? 'desc' : 'asc');
            rows.forEach(r => tbody.appendChild(r));
        }}
    </script>
</body>
</html>
"""


def render_json_report(batch_result: Union[BatchResult, Dict[str, Any]]) -> str:
    """Format batch results as pretty-printed JSON."""
    data = batch_result.to_dict() if hasattr(batch_result, "to_dict") else batch_result
    return json.dumps(data, indent=2)


def save_report(batch_result: Union[BatchResult, Dict[str, Any]], output_path: str) -> None:
    """Save either an HTML or JSON report to disk based on file extension."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if output_path.lower().endswith(".html") or output_path.lower().endswith(".htm"):
        content = render_html_report(batch_result)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        content = render_json_report(batch_result)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
