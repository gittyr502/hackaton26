"""Turning a rule written in Hebrew into a structured rule, and trying it on the forms already in the system.

Claude only translates the text (text-only call, no form data is sent). What it returns is checked:
unknown fields or ops are refused, and a sender that is not in the closed list becomes a question for
the manager, never a guess. The dry run is deterministic (validators/rules.py) over current values,
so human corrections count.
"""
import json
from collections import Counter
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.fields import FIELD_NAMES, MULTI_FIELDS, OPTIONAL_FIELDS
from app.models import Field, Form
from validators.rules import (CHECKS, FIELD_LABELS_HE, OPS, describe_he, describe_parts, evaluate,
                              referenced_fields, validate_spec)
from validators.senders import canonical_names, match_sender

SYSTEM = (
    "You convert validation rules that a virology lab manager writes in Hebrew into a structured rule "
    "over the fields of a commitment form. Use only the fields and operations listed. "
    "If a term in the rule cannot be mapped with certainty to a listed field or value, do not guess: "
    "return no spec, list the unclear terms in unknown_terms, and ask one short question in Hebrew."
)

TOOL = {
    "name": "record_rule",
    "description": "Record the structured rule, or the terms that could not be mapped.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "short Hebrew title for the rule"},
            "spec": {
                "type": ["object", "null"],
                "properties": {
                    "combine": {"type": "string", "enum": ["all", "any"]},
                    "when": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": FIELD_NAMES},
                            "op": {"type": "string", "enum": list(OPS)},
                            "value": {},
                        },
                        "required": ["field", "op"],
                    }},
                    "then": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": FIELD_NAMES},
                            "check": {"type": "string", "enum": list(CHECKS)},
                            "arg": {},
                        },
                        "required": ["field", "check"],
                    },
                },
                "required": ["when", "then"],
            },
            "unknown_terms": {"type": "array", "items": {"type": "string"}},
            "question": {"type": ["string", "null"]},
        },
        "required": ["name"],
    },
}


def catalog(senders_cfg: Dict[str, Any]) -> str:
    lines = ["Fields (name: Hebrew label):"]
    for n in FIELD_NAMES:
        tags = [t for t, on in (("list", n in MULTI_FIELDS), ("optional", n in OPTIONAL_FIELDS)) if on]
        lines.append(f"- {n}: {FIELD_LABELS_HE.get(n, n)}" + (f" ({', '.join(tags)})" if tags else ""))
    lines.append("Senders (canonical name: aliases) — the sender field holds the canonical name:")
    for s in senders_cfg.get("senders", []):
        lines.append(f"- {s['name']}: {', '.join(s.get('aliases', []))}")
    lines += [
        "Operations in when: eq, neq, in (value is a list), contains, empty, not_empty (no value).",
        "Checks in then: required, forbidden (must be empty), regex (arg = pattern), "
        "in_list (arg = list), date_not_before (arg = YYYY-MM-DD).",
        "Example: 'אם הקופה מכבי והבדיקה PCR – חובה מספר הפניה' -> "
        '{"combine":"all","when":[{"field":"sender","op":"eq","value":"מכבי"},'
        '{"field":"test_type","op":"eq","value":"PCR"}],"then":{"field":"referral_number","check":"required"}}',
    ]
    return "\n".join(lines)


def _unknown_senders(spec: Dict[str, Any], senders_cfg: Dict[str, Any]) -> List[str]:
    """Sender values the closed list does not know (also rewrites known ones to their canonical name)."""
    unknown = []
    known = set(canonical_names(senders_cfg))
    for cond in spec.get("when") or []:
        if cond.get("field") != "sender" or cond.get("op") in ("empty", "not_empty"):
            continue
        values = cond.get("value") if isinstance(cond.get("value"), list) else [cond.get("value")]
        out = []
        for v in values:
            canonical = v if v in known else match_sender(str(v or ""), senders_cfg)[0]
            if canonical is None:
                unknown.append(str(v))
            out.append(canonical or v)
        cond["value"] = out if isinstance(cond.get("value"), list) else out[0]
    return unknown


def explain(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {"description": describe_he(spec), "parts": describe_parts(spec)}


async def parse_rule(text: str, client: Any, senders_cfg: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    """{name, spec | None, description, parts, unknown_terms, question, errors}."""
    kw = {"model": model} if model else {}
    got = await client.call_tool_text(
        prompt=f"{catalog(senders_cfg)}\n\nThe rule:\n{text.strip()}", tool=TOOL, system=SYSTEM, **kw)
    spec = got.get("spec") if isinstance(got.get("spec"), dict) else None
    unknown = [str(t) for t in got.get("unknown_terms") or []]
    out: Dict[str, Any] = {"name": (got.get("name") or text.strip())[:80], "spec": None, "description": None,
                           "parts": None, "unknown_terms": unknown, "question": got.get("question"), "errors": []}
    if spec is None:
        return out
    spec.setdefault("combine", "all")
    errors = validate_spec(spec)
    if errors:
        out["errors"] = errors
        return out
    bad_senders = _unknown_senders(spec, senders_cfg)
    if bad_senders:
        out["unknown_terms"] = unknown + bad_senders
        out["question"] = out["question"] or f"הגורם השולח '{bad_senders[0]}' לא נמצא ברשימה. למי התכוונת?"
        return out
    out["spec"] = spec
    out.update(explain(spec))
    return out


# ---------- running a rule over the forms in the system ----------

def _current_forms(s: Session, workflows: Optional[List[str]] = None) -> Dict[int, Dict[str, Any]]:
    """form id -> {field: current value} for every read commitment (merged pages counted once)."""
    q = select(Form).where(Form.status == "done", Form.doc_type == "commitment",
                           Form.parent_form_id == None)  # noqa: E711
    if workflows is not None:
        q = q.where(Form.workflow.in_(workflows))
    forms = {f.id: f for f in s.exec(q).all()}
    values: Dict[int, Dict[str, Any]] = {i: {} for i in forms}
    if forms:
        for fld in s.exec(select(Field).where(Field.form_id.in_(list(forms)))).all():
            values[fld.form_id][fld.name] = json.loads(fld.value) if fld.value is not None else None
    return values


def violating_forms(s: Session, spec: Dict[str, Any], senders_cfg: Dict[str, Any],
                    workflows: Optional[List[str]] = None) -> List[int]:
    return [fid for fid, vals in _current_forms(s, workflows).items() if evaluate(spec, vals, senders_cfg)]


def dry_run(s: Session, spec: Dict[str, Any], senders_cfg: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
    """What the rule would have flagged among the forms already read (nothing is changed)."""
    from app.api.workflow import form_summaries

    values = _current_forms(s)
    flagged = [fid for fid, vals in values.items() if evaluate(spec, vals, senders_cfg)]
    by_sender = Counter(str(values[fid].get("sender") or "—") for fid in flagged)
    coverage = {n: sum(1 for v in values.values() if v.get(n) not in (None, "", [])) for n in referenced_fields(spec)}
    warnings = [{"code": "field_never_read", "field": n} for n, c in coverage.items() if values and c == 0]
    examples = form_summaries(s, [s.get(Form, fid) for fid in sorted(flagged, reverse=True)[:limit]])
    return {"checked": len(values), "flagged": len(flagged), "by_sender": dict(by_sender.most_common()),
            "field_coverage": coverage, "warnings": warnings, "examples": examples}
