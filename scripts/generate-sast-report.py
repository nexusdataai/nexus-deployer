#!/usr/bin/env python3
"""Generate the Internal SAST findings PDF for Nexus AI Deployer.

Runs Bandit, Semgrep and detect-secrets, buckets the findings by severity
(matching the bucket definitions in the original report) and renders a PDF
with the same layout/branding as
`kube-operator/tests/SAST-Internal-nexus-deployer.pdf`.

Usage
-----
    pip install --break-system-packages bandit==1.8.6 semgrep==1.136.0 \\
        detect-secrets==1.5.0 reportlab>=4.0
    python3 scripts/generate-sast-report.py \\
        [--output kube-operator/tests/SAST-Internal-nexus-deployer.pdf] \\
        [--skip-scan]   # reuse cached JSON in /tmp/sast-report-work/

The generated PDF is INTERNAL ONLY (header banner enforces that). Do not
share with clients; quote only the attestation produced by
`scripts/sast-attest.sh`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "kube-operator" / "tests" / "SAST-Internal-nexus-deployer.pdf"
WORK = Path("/tmp/sast-report-work")

EXCLUDE_GLOBS = [
    ".git",
    "node_modules",
    "frontend/node_modules",
    "electron/node_modules",
    "frontend/dist",
    "backend/venv",
    "backend/.venv",
    ".kiro",
    "docs/_build",
]
EXCLUDE_FILE_RE = (
    r"go-containerregistry_.*\.tar\.gz|velero-.*\.tar\.gz|"
    r"node_modules/|\.git/|frontend/dist/|backend/venv/"
)

BANDIT_TOOL = "Bandit"
SEMGREP_TOOL = "Semgrep"
DETECT_SECRETS_TOOL = "detect-secrets"


# ---------------------------------------------------------------------------
# Scanner runners
# ---------------------------------------------------------------------------

def run_bandit(work: Path) -> dict:
    out = work / "bandit.json"
    cmd = [
        "bandit", "-c", str(REPO_ROOT / ".bandit.yaml"),
        "-r", "backend", "kube-operator/src", "bssmagic-image",
        "-f", "json", "-o", str(out), "--exit-zero",
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    with out.open() as f:
        return json.load(f)


def run_semgrep(work: Path) -> dict:
    out = work / "semgrep.json"
    cmd = [
        "semgrep", "--config", "p/security-audit",
        "--json", "--output", str(out), "--metrics=off", "--quiet",
    ]
    for ex in EXCLUDE_GLOBS:
        cmd += ["--exclude", ex]
    cmd.append(".")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    with out.open() as f:
        return json.load(f)


def run_detect_secrets(work: Path) -> dict:
    out = work / "detect-secrets.json"
    cmd = [
        "detect-secrets", "scan",
        "--exclude-files", EXCLUDE_FILE_RE,
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    out.write_text(result.stdout)
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Bucketing -- matches the original report's "Severity bucket definitions"
# ---------------------------------------------------------------------------

NOISY_BANDIT_IDS = {"B101", "B106", "B110", "B603", "B105", "B607", "B404", "B405", "B107", "B311"}


def bucket_bandit(report: dict) -> tuple[list, list, list, dict]:
    blocking, review, noise = [], [], []
    rule_counter: Counter = Counter()
    for r in report.get("results", []):
        sev = r.get("issue_severity", "LOW")
        rid = r.get("test_id", "?")
        rule_counter[rid] += 1
        item = {
            "rule_name": r.get("test_name", rid),
            "severity": sev,
            "id": rid,
            "cwe": (r.get("issue_cwe") or {}).get("id"),
            "confidence": r.get("issue_confidence", ""),
            "file": r.get("filename", "?"),
            "line": r.get("line_number", 0),
            "text": r.get("issue_text", ""),
        }
        if sev == "HIGH":
            blocking.append(item)
        elif sev == "MEDIUM":
            review.append(item)
        else:
            noise.append(item)
    return blocking, review, noise, dict(rule_counter)


def bucket_semgrep(report: dict) -> tuple[list, list, list]:
    blocking, review, noise = [], [], []
    for r in report.get("results", []):
        sev = (r.get("extra") or {}).get("severity", "INFO")
        check_id = r.get("check_id", "?")
        short = check_id.rsplit(".", 1)[-1]
        meta = (r.get("extra") or {}).get("metadata", {}) or {}
        cwe = meta.get("cwe")
        if isinstance(cwe, list):
            cwe = cwe[0] if cwe else None
        item = {
            "rule_name": short[:4] if short else "?",
            "severity": sev,
            "id": check_id,
            "cwe": cwe,
            "file": r.get("path", "?"),
            "line": (r.get("start") or {}).get("line", 0),
            "text": (r.get("extra") or {}).get("message", "").strip(),
        }
        if sev == "ERROR":
            blocking.append(item)
        elif sev == "WARNING":
            review.append(item)
        else:
            noise.append(item)
    return blocking, review, noise


def bucket_detect_secrets(report: dict) -> tuple[list, list, list]:
    blocking, review, noise = [], [], []
    for fname, entries in (report.get("results") or {}).items():
        for e in entries:
            item = {
                "rule_name": e.get("type", "Secret"),
                "severity": "MEDIUM",
                "id": e.get("type", "Secret"),
                "cwe": "CWE-798",
                "file": fname,
                "line": e.get("line_number", 0),
                "text": (
                    f"Potential secret of type '{e.get('type')}' detected. "
                    "is_verified=False. Manual triage required (high false-"
                    "positive rate on test fixtures, examples, hex-like config "
                    "values)."
                ),
            }
            review.append(item)
    return blocking, review, noise


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_pdf(
    output: Path,
    *,
    bandit_b: list, bandit_r: list, bandit_n: list, bandit_top_rules: dict,
    semgrep_b: list, semgrep_r: list, semgrep_n: list,
    secrets_b: list, secrets_r: list, secrets_n: list,
    sha: str, branch: str,
) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
        TableStyle, PageBreak,
    )

    output.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Banner", parent=styles["Normal"],
                              fontSize=8, textColor=colors.darkred,
                              alignment=1, leading=10))
    styles.add(ParagraphStyle("Header", parent=styles["Heading1"],
                              fontSize=18, spaceAfter=8))
    styles.add(ParagraphStyle("H2", parent=styles["Heading2"],
                              fontSize=13, spaceAfter=4))
    styles.add(ParagraphStyle("H3", parent=styles["Heading3"],
                              fontSize=11, spaceAfter=2, textColor=colors.darkblue))
    styles.add(ParagraphStyle("Finding", parent=styles["Normal"],
                              fontSize=9, leading=11))
    styles.add(ParagraphStyle("FindingHead", parent=styles["Normal"],
                              fontSize=9.5, leading=12,
                              fontName="Helvetica-Bold"))

    page_w, page_h = LETTER
    margin = 0.6 * inch
    frame = Frame(margin, margin, page_w - 2 * margin, page_h - 2 * margin,
                  showBoundary=0, leftPadding=0, rightPadding=0,
                  topPadding=24, bottomPadding=24)

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.darkred)
        banner = ("I N T E R N A L — S T A R H U B  C A L L S E N S E "
                  "— D O  N O T  D I S T R I B U T E  T O  C L I E N T")
        canvas.drawCentredString(page_w / 2, page_h - 24, banner)
        canvas.setFillColor(colors.grey)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(margin, 18, f"Page {doc.page}    I N T E R N A L  O N L Y")
        canvas.drawRightString(page_w - margin, 18,
                               f"-- {doc.page} of N --")
        canvas.restoreState()

    doc = BaseDocTemplate(str(output), pagesize=LETTER,
                          leftMargin=margin, rightMargin=margin,
                          topMargin=margin, bottomMargin=margin,
                          title="INTERNAL SAST FINDINGS - Nexus AI Deployer")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=_on_page)])

    story: list = []

    # ---- Title page ------------------------------------------------------
    story.append(Paragraph("INTERNAL SAST FINDINGS", styles["Header"]))
    story.append(Paragraph("Nexus AI Deployer", styles["H2"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Static analysis findings on the source tree at the indicated commit.",
        styles["Normal"]))
    story.append(Spacer(1, 12))

    today = _dt.date.today().isoformat()
    meta = [
        ["Repository", "nexus-deployer"],
        ["Branch", branch],
        ["Source SHA", sha],
        ["Scan date", today],
        ["Tools used", "Bandit, Semgrep, detect-secrets"],
    ]
    t = Table(meta, colWidths=[1.5 * inch, 5.5 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>CONFIDENTIAL · INTERNAL ENGINEERING USE ONLY · DO NOT DISTRIBUTE "
        "TO ANY CLIENT · CONTAINS RAW SOURCE-LEVEL FINDINGS COVERED "
        "BY IP PROTECTION POLICY</b>", styles["Normal"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "INTERNAL USE ONLY — THIS REPORT CONTAINS SOURCE-LEVEL FINDINGS THAT "
        "MUST NEVER BE SHARED WITH CLIENTS. USE IT AS THE BASIS FOR THE SAST "
        "ATTESTATION, NOT AS THE SAST ATTESTATION ITSELF.", styles["Normal"]))
    story.append(Spacer(1, 14))

    # ---- Executive summary -----------------------------------------------
    blocking_total = len(bandit_b) + len(semgrep_b) + len(secrets_b)
    review_total = len(bandit_r) + len(semgrep_r) + len(secrets_r)
    story.append(Paragraph("Executive summary", styles["H2"]))
    story.append(Paragraph(
        f"<b>{blocking_total}</b> blocking findings need remediation before "
        f"release. Plus <b>{review_total}</b> MEDIUM/WARNING items for "
        "triage. Do not issue a clean SAST attestation until the blocking "
        "count is zero.", styles["Normal"]))
    story.append(Spacer(1, 8))

    summary = [
        ["TOOL", "PURPOSE", "TOTAL", "HIGH/CRIT", "MED/WARN", "LOW/INFO"],
        ["Bandit (1.8.6)", "Python static analysis (SAST)",
         str(len(bandit_b) + len(bandit_r) + len(bandit_n)),
         f"{len(bandit_b)} blocking", f"{len(bandit_r)} review",
         f"{len(bandit_n)} noise"],
        ["Semgrep (1.136.0)", "Multi-language static analysis (SAST)",
         str(len(semgrep_b) + len(semgrep_r) + len(semgrep_n)),
         f"{len(semgrep_b)} blocking", f"{len(semgrep_r)} review",
         f"{len(semgrep_n)} noise"],
        ["detect-secrets (1.5.0)", "Hardcoded credential / secret scanning",
         str(len(secrets_b) + len(secrets_r) + len(secrets_n)),
         f"{len(secrets_b)} blocking", f"{len(secrets_r)} review",
         f"{len(secrets_n)} noise"],
    ]
    t = Table(summary, colWidths=[1.3 * inch, 2.4 * inch, 0.7 * inch,
                                   1.1 * inch, 1.0 * inch, 0.9 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Severity bucket definitions", styles["H3"]))
    story.append(Paragraph(
        "<b>HIGH/CRIT (blocking)</b>: Bandit HIGH, Semgrep ERROR, npm audit "
        "CRITICAL+HIGH. These must be remediated before any merge or release. "
        "<b>MED/WARN (review)</b>: Bandit MEDIUM, Semgrep WARNING, npm audit "
        "MODERATE. Triaged on a case-by-case basis; many require code-context "
        "interpretation. <b>LOW/INFO (noise)</b>: Bandit LOW, Semgrep INFO. "
        "Tracked for trend analysis but not gated.", styles["Normal"]))
    story.append(PageBreak())

    # ---- Tool sections ---------------------------------------------------
    def _section(title: str, total: int, blocking: list, review: list,
                 noise_count: int, top_rules: dict | None = None,
                 description: str = "") -> None:
        story.append(Paragraph(title, styles["H2"]))
        if description:
            story.append(Paragraph(description, styles["Normal"]))
            story.append(Spacer(1, 6))

        story.append(Paragraph(f"Blocking ({len(blocking)})", styles["H3"]))
        if not blocking:
            story.append(Paragraph("None.", styles["Finding"]))
        for f in blocking:
            _render_finding(f, story, styles)
        story.append(Spacer(1, 6))

        story.append(Paragraph(f"Review ({len(review)})", styles["H3"]))
        if not review:
            story.append(Paragraph("None.", styles["Finding"]))
        for f in review:
            _render_finding(f, story, styles)
        story.append(Spacer(1, 6))

        if noise_count:
            story.append(Paragraph(
                f"Noise (LOW/INFO) — {noise_count} suppressed",
                styles["H3"]))
            if top_rules:
                rows = [["RULE", "OCCURRENCES"]]
                for rid, n in sorted(top_rules.items(),
                                     key=lambda kv: -kv[1])[:10]:
                    rows.append([rid, str(n)])
                t = Table(rows, colWidths=[1.5 * inch, 1.5 * inch])
                t.setStyle(TableStyle([
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                    ("BOX", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]))
                story.append(t)
        story.append(PageBreak())

    _section(
        "Bandit findings",
        len(bandit_b) + len(bandit_r) + len(bandit_n),
        bandit_b, bandit_r, len(bandit_n),
        top_rules=bandit_top_rules,
        description=(f"Python static analysis (SAST) · "
                     f"{len(bandit_b) + len(bandit_r) + len(bandit_n)} "
                     "total finding(s)."),
    )
    _section(
        "Semgrep findings",
        len(semgrep_b) + len(semgrep_r) + len(semgrep_n),
        semgrep_b, semgrep_r, len(semgrep_n),
        description=(f"Multi-language static analysis (SAST) · "
                     f"{len(semgrep_b) + len(semgrep_r) + len(semgrep_n)} "
                     "total finding(s)."),
    )
    _section(
        "detect-secrets findings",
        len(secrets_b) + len(secrets_r) + len(secrets_n),
        secrets_b, secrets_r, len(secrets_n),
        description=(f"Hardcoded credential / secret scanning · "
                     f"{len(secrets_b) + len(secrets_r) + len(secrets_n)} "
                     "total finding(s)."),
    )

    story.append(Paragraph(
        "END OF REPORT. FINDINGS HERE MUST BE REMEDIATED, SUPPRESSED WITH "
        "JUSTIFICATION, OR ACCEPTED WITH SIGN-OFF BEFORE BEING SUMMARISED IN "
        "THE CLIENT-FACING SAST ATTESTATION. THE ATTESTATION MUST NEVER QUOTE "
        "RAW FINDINGS FROM THIS DOCUMENT.", styles["FindingHead"]))

    doc.build(story)


def _render_finding(f: dict, story: list, styles: dict) -> None:
    from reportlab.platypus import Paragraph, Spacer
    head = (
        f"<b>{_escape(f['rule_name'])}</b> "
        f"&nbsp;&nbsp;<font color='#666666'>{f['severity']}</font>"
    )
    sub_parts = [_escape(f["id"])]
    if f.get("cwe"):
        sub_parts.append(f"CWE-{_escape(str(f['cwe']))}")
    if f.get("confidence"):
        sub_parts.append(f"confidence {_escape(f['confidence'])}")
    sub_parts.append(f"{_escape(f['file'])}:{f['line']}")
    sub = " · ".join(sub_parts)
    story.append(Paragraph(head, styles["FindingHead"]))
    story.append(Paragraph(f"<font size='8' color='#444444'>{sub}</font>",
                           styles["Finding"]))
    story.append(Paragraph(_escape(f["text"]), styles["Finding"]))
    story.append(Spacer(1, 4))


def _escape(s: Any) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-scan", action="store_true",
                        help="Reuse cached JSON in /tmp/sast-report-work/")
    args = parser.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)

    if not args.skip_scan:
        for tool in ("bandit", "semgrep", "detect-secrets"):
            if shutil.which(tool) is None:
                print(f"[generate-sast-report] ERROR: '{tool}' not on PATH. "
                      "Install the scanners first (see module docstring).",
                      file=sys.stderr)
                sys.exit(2)
        print("[generate-sast-report] Running Bandit...")
        bandit = run_bandit(WORK)
        print("[generate-sast-report] Running Semgrep (this can take a while)...")
        semgrep = run_semgrep(WORK)
        print("[generate-sast-report] Running detect-secrets...")
        ds = run_detect_secrets(WORK)
    else:
        bandit = json.loads((WORK / "bandit.json").read_text())
        semgrep = json.loads((WORK / "semgrep.json").read_text())
        ds = json.loads((WORK / "detect-secrets.json").read_text())

    bandit_b, bandit_r, bandit_n, top_rules = bucket_bandit(bandit)
    semgrep_b, semgrep_r, semgrep_n = bucket_semgrep(semgrep)
    secrets_b, secrets_r, secrets_n = bucket_detect_secrets(ds)

    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT,
            text=True).strip()
    except Exception:
        sha = "unknown"
        branch = "unknown"

    print(f"[generate-sast-report] Rendering PDF -> {args.output}")
    render_pdf(
        args.output,
        bandit_b=bandit_b, bandit_r=bandit_r, bandit_n=bandit_n,
        bandit_top_rules=top_rules,
        semgrep_b=semgrep_b, semgrep_r=semgrep_r, semgrep_n=semgrep_n,
        secrets_b=secrets_b, secrets_r=secrets_r, secrets_n=secrets_n,
        sha=sha, branch=branch,
    )
    print("[generate-sast-report] Done.")


if __name__ == "__main__":
    main()
