"""Check a campaign CSV before it is uploaded to a dialler.

Two kinds of check:

  1. FORMAT - the things a dialler rejects: no phone column, a number without
     '+', the same number twice. Many diallers reject the whole file rather
     than the bad row, so one stray number costs you the upload.

  2. COVERAGE - the thing no dialler checks. If the agent's prompt says
     {{probe_line}} and that column is empty in a fifth of the rows, the file
     uploads clean and the problem only shows up as a wrong sentence on a live
     call. So this reads the prompt files, finds every template variable they
     speak, and reports how well the CSV fills each one.

Template syntax understood:  {{name}}  and  {{name | fallback:some words}}
"""
import csv
import re
from pathlib import Path

TEMPLATE_VAR = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*(?:\|\s*fallback\s*:\s*([^}]*?)\s*)?\}\}")
PHONE = re.compile(r"\+\d{8,15}")


def template_columns(prompts_dir: Path, strip_prefix: str = "initial_context.") -> dict | None:
    """Map every template variable in the prompt files to its fallback (or None).

    `strip_prefix` handles platforms that namespace CSV columns, so
    {{initial_context.candidate_name}} and {{candidate_name}} mean one column.
    Other dotted names are runtime values, not CSV columns, and are skipped.
    """
    prompts_dir = Path(prompts_dir)
    if not prompts_dir.is_dir():
        return None
    found = {}
    for p in sorted(prompts_dir.rglob("*.txt")) + sorted(prompts_dir.rglob("*.md")):
        for m in TEMPLATE_VAR.finditer(p.read_text(encoding="utf-8")):
            name = m.group(1)
            if strip_prefix and name.startswith(strip_prefix):
                name = name[len(strip_prefix):]
            if "." in name:
                continue
            found.setdefault(name, m.group(2) if m.group(2) else None)
    return found


def check(path: Path, prompts_dir: Path | None = None, log=print) -> int:
    """Validate one CSV. Returns 0 if it is safe to upload, 1 otherwise."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 2:
        log(f"FAIL  {path.name}: needs a header row and at least one data row")
        return 1

    raw_headers, data = rows[0], rows[1:]
    headers = [h.strip().lower() for h in raw_headers]
    problems, warnings, coverage = [], [], []

    if "phone_number" not in headers:
        log(f"FAIL  {path.name}: no phone_number column")
        return 1
    idx = headers.index("phone_number")

    for raw, norm in zip(raw_headers, headers):
        if raw != norm:
            warnings.append(f"header '{raw}' is not lowercase/trimmed; prompts must use '{norm}'")
    if len(set(headers)) != len(headers):
        problems.append("duplicate column names")

    seen = {}
    for i, row in enumerate(data, start=2):
        if len(row) <= idx or not row[idx].strip():
            warnings.append(f"row {i}: blank phone_number, row cannot be dialled")
            continue
        phone = row[idx].strip()
        if not PHONE.fullmatch(phone):
            problems.append(f"row {i}: '{phone}' is not + followed by 8-15 digits")
        if phone in seen:
            problems.append(f"row {i}: duplicate phone number, same as row {seen[phone]}")
        else:
            seen[phone] = i

    if prompts_dir is not None:
        template = template_columns(prompts_dir)
        if template is None:
            warnings.append(f"no prompts folder at {prompts_dir}, skipped column coverage")
        for col, fallback in sorted((template or {}).items()):
            if col not in headers:
                # A missing column is never intended: a renamed column looks
                # exactly like this, and the fallback would fire on every call.
                problems.append(
                    f"prompt speaks {{{{{col}}}}} but this CSV has no '{col}' column"
                    + (f" (every call would say the fallback '{fallback}')" if fallback else ""))
                continue
            j = headers.index(col)
            empty = [i for i, r in enumerate(data, start=2) if len(r) <= j or not r[j].strip()]
            if not empty:
                coverage.append(f"{col}: filled in all {len(data)} rows")
            elif fallback is None:
                problems.append(f"'{col}' is empty in {len(empty)} row(s) and the prompt has no "
                                f"fallback for it: rows {empty[:5]}")
            else:
                coverage.append(f"{col}: EMPTY in {len(empty)}/{len(data)} rows -> those calls "
                                f"say the fallback '{fallback}' (rows {empty[:5]})")

    log(f"{path.name}: {len(data)} data rows, {len(headers)} columns, {len(seen)} unique numbers")
    for c in coverage:
        log(f"  cover {c}")
    for w in warnings:
        log(f"  warn  {w}")
    for p in problems:
        log(f"  FAIL  {p}")
    log("  OK, safe to upload\n" if not problems else "  REJECTED, fix the above\n")
    return 1 if problems else 0
