"""Accuracy eval against eval/ground_truth.csv.

    python -m eval.run [--no-double-check]

Runs the pipeline (no DB) over eval/samples/ and reports per field: accuracy,
hidden errors (marked ok but wrong — the headline metric), flag rate, and false empty.
"""
import argparse
import asyncio
import csv
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.fields import FIELD_NAMES, LEVEL_OK, LEVEL_REVIEW, MULTI_FIELDS  # noqa: E402
from pipeline.base import FormDoc  # noqa: E402
from pipeline.normalizers import normalize_field, values_equal  # noqa: E402
from pipeline.runner import build_context, load_stages, run_docs  # noqa: E402

EVAL_DIR = ROOT / "eval"
SAMPLES = EVAL_DIR / "samples"
GROUND_TRUTH = EVAL_DIR / "ground_truth.csv"
REPORT = EVAL_DIR / "report.md"
SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif"}
SKIP = "*"  # ground-truth cell value meaning "don't score this field"


def load_truth(senders_cfg: Dict[str, Any]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    truth = {}
    with open(GROUND_TRUTH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["filename"].strip(), int(row.get("page") or 1))
            rec = {}
            for name in FIELD_NAMES:
                if row.get(name) is None:
                    continue  # no such column (a field added after this table was written): not scored
                raw = (row.get(name) or "").strip()
                if raw == SKIP:
                    continue  # not scored for this row

                if name in MULTI_FIELDS:
                    raw = [x.strip() for x in raw.split(";") if x.strip()] or None
                rec[name], _ = normalize_field(name, raw or None, senders_cfg)
            truth[key] = rec
    return truth


async def run_pipeline(files: List[Path], double_check: bool) -> List[FormDoc]:
    settings = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="eval_"))
    ctx = build_context(settings, batch_dir=tmp)
    ctx.pipeline_cfg = dict(ctx.pipeline_cfg, double_check={"enabled": double_check})
    stages = load_stages(ctx.pipeline_cfg)
    results: List[FormDoc] = []
    docs = [FormDoc(batch_id=0, source_file_id=i, file_path=str(p)) for i, p in enumerate(files)]
    for d in docs:  # one at a time per file so a broken file does not abort the run
        try:
            await run_docs(stages, [d], ctx, persist=False, results=results)
        except Exception as e:
            print(f"  ! {files[d.source_file_id].name}: {type(e).__name__}")
    return results


def evaluate(results: List[FormDoc], files: List[Path], truth) -> Tuple[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    hw: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # fields read as handwritten
    hidden_examples: List[str] = []
    seen = set()
    failed = 0
    for doc in results:
        key = (files[doc.source_file_id].name, doc.page_index + 1)
        if key not in truth:
            continue
        seen.add(key)
        if doc.form_type == "__failed__":
            failed += 1
        for name in FIELD_NAMES:
            if name not in truth[key]:
                continue
            exp = truth[key][name]
            fr = doc.fields.get(name)
            got = fr.value if fr else None
            level = fr.level if fr else "empty"
            correct = values_equal(got, exp)
            groups = [stats[name]] + ([hw[name]] if fr and fr.handwritten else [])
            for st in groups:
                st["total"] += 1
                st["correct"] += correct
                if level == LEVEL_REVIEW:
                    st["flagged"] += 1
                if level == LEVEL_OK and not correct:
                    st["hidden"] += 1
                if got is None and exp is not None:
                    st["false_empty"] += 1
            if level == LEVEL_OK and not correct:
                hidden_examples.append(f"{key[0]} p{key[1]} · {name}")
    missing = [k for k in truth if k not in seen]

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.1f}%" if b else "—"

    lines = [
        f"# Eval report — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Forms evaluated: {len(seen)} · failed: {failed} · ground-truth rows without a result: {len(missing)}",
        "",
        "| Field | Accuracy | Hidden errors | Flag rate | False empty |",
        "|---|---|---|---|---|",
    ]
    tot = defaultdict(int)
    for name in FIELD_NAMES:
        st = stats[name]
        for k in ("total", "correct", "hidden", "flagged", "false_empty"):
            tot[k] += st[k]
        lines.append(f"| {name} | {pct(st['correct'], st['total'])} | {st['hidden']} | "
                     f"{pct(st['flagged'], st['total'])} | {st['false_empty']} |")
    lines.append(f"| **all** | **{pct(tot['correct'], tot['total'])}** | **{tot['hidden']}** | "
                 f"**{pct(tot['flagged'], tot['total'])}** | **{tot['false_empty']}** |")
    lines += ["", f"**Hidden errors: {tot['hidden']}** (target: 0)"]
    if hw:
        lines += ["", "## Handwritten fields (as reported by the model)", "",
                  "| Field | Count | Accuracy | Hidden errors | Flag rate | False empty |",
                  "|---|---|---|---|---|---|"]
        for name in FIELD_NAMES:
            if name in hw:
                st = hw[name]
                lines.append(f"| {name} | {st['total']} | {pct(st['correct'], st['total'])} | {st['hidden']} | "
                             f"{pct(st['flagged'], st['total'])} | {st['false_empty']} |")
    if hidden_examples:
        lines += ["", "## Hidden errors", ""] + [f"- {h}" for h in hidden_examples]
    if missing:
        lines += ["", "## Missing results", ""] + [f"- {f} p{p}" for f, p in missing]
    return "\n".join(lines) + "\n", dict(tot)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-double-check", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    truth = load_truth(settings.senders)
    files = sorted(p for p in SAMPLES.iterdir() if p.suffix.lower() in SUPPORTED) if SAMPLES.exists() else []
    if not truth or not files:
        print(f"Nothing to evaluate: {len(files)} sample files in {SAMPLES}, "
              f"{len(truth)} rows in {GROUND_TRUTH.name}.")
        print("Add forms to eval/samples/ and their values to eval/ground_truth.csv "
              "(multi-values separated by ';').")
        return 1
    print(f"Running pipeline on {len(files)} files...")
    results = asyncio.run(run_pipeline(files, double_check=not args.no_double_check))
    report, _ = evaluate(results, files, truth)
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
