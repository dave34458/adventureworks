import re
from datetime import UTC, datetime

from tests.config import RESULTS_FILE

TC_PATTERN = re.compile(r"test_tc(\d{2})_")
RESULTS = {}


def tc_id_from_name(name):
    match = TC_PATTERN.search(name)
    return f"TC-{match.group(1)}" if match else None


def short_detail(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return "no details"
    detail = lines[-1]
    detail = re.sub(r"\x1b\[[0-9;]*m", "", detail)
    return detail.replace("|", "/")[:240]


def actual_result(entry):
    if entry is None:
        return "Not run"
    outcome = entry["outcome"]
    details = entry.get("details", [])
    if outcome == "passed":
        return "Pass"
    if outcome == "skipped":
        return "Skipped — " + (details[-1] if details else "no reason")
    return "Fail — " + (details[-1] if details else "no details")


def write_results(results, exit_status):
    source_lines = RESULTS_FILE.read_text(encoding="utf-8").splitlines() if RESULTS_FILE.exists() else []
    passes = sum(1 for value in results.values() if value["outcome"] == "passed")
    failures = sum(1 for value in results.values() if value["outcome"] == "failed")
    skips = sum(1 for value in results.values() if value["outcome"] == "skipped")
    summary = f"Pass: {passes} · Fail: {failures} · Skipped: {skips} · Not run: {12 - len(results)}"
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    header = [
        "# AdventureWorks Reporting System — Test Results",
        "",
        f"Generated: {generated}",
        "Command: `python -m pytest tests -q`",
        f"pytest exit status: {exit_status}",
        f"Summary: {summary}",
        f"Status: generated from the last pytest run ({generated}).",
        "",
    ]

    output = []
    in_matrix = True
    for line in source_lines:
        if line.startswith("# "):
            output.extend(header)
            continue
        if line.startswith(("Generated:", "Command:", "pytest exit status:", "Summary:", "Source matrix:", "Status:")):
            continue
        if line.startswith("## Playwright mapping"):
            in_matrix = False
        if line.startswith("3. `Actual Result` will be filled"):
            output.append("3. `Actual Result` is filled from the last pytest run.")
            continue
        if in_matrix and line.startswith("| TC-"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4:
                output.append(f"| {cells[0]} | {cells[1]} | {cells[2]} | {actual_result(results.get(cells[0]))} |")
                continue
        output.append(line)

    if not source_lines:
        output.extend(header)

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return RESULTS_FILE
