"""Learning from human corrections, so the same mistake is not made twice.

Corrections (app.models.Correction) become Lessons, used in three places:
- Normalize: a sender spelling that reviewers always fixed to the same canonical name is mapped directly.
- Extract / double-check: the prompt lists mistakes reviewers keep fixing (confused characters, values
  missed or invented, sender and date examples). Only patterns go in, never a patient's name or ID.
- Confidence: a field the model gets wrong with high confidence too often is no longer trusted blindly.

Only corrections on approved forms count (an approver has seen them), and only the most recent ones,
so a lesson fades once the mistake stops happening.
"""
import difflib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlmodel import Session, select

from app.fields import FIELD_NAMES
from app.models import Correction, Form
from app.workflow import APPROVED
from pipeline.normalizers import to_display_date
from validators.senders import canonical_names, normalize_for_match

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "min_confirmations": 2,  # times the same fix must be seen before it is applied or put in the prompt
    "window": 500,  # most recent corrections considered
    "window_forms": 200,  # most recent approved forms used to measure how often a field is wrong
    "min_samples": 20,  # approved forms needed before a field's error rate means anything
    "review_rate": 0.1,  # confident-but-wrong rate above which a field always goes to review
    "max_lines": 12,
}
CHAR_FIELDS = ("id_number", "full_name")  # where a misread character is a meaningful lesson
EXAMPLE_FIELDS = ("sender", "receipt_date")  # closed / low-sensitivity values: shown to the model as examples

Pair = Tuple[str, str, int]


def _load(v: Optional[str]) -> Any:
    return None if v is None else json.loads(v)


def _show(name: str, v: Any) -> str:
    if name == "receipt_date" and isinstance(v, str):
        return to_display_date(v) or v
    return str(v)


def char_confusions(read: str, right: str) -> List[Tuple[str, str]]:
    """Single characters (or a pair) swapped for others: ('1', '7') = the model read 1 where 7 was written."""
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, read, right).get_opcodes():
        if op == "replace" and i2 - i1 == j2 - j1 and i2 - i1 <= 2:
            out += [(a, b) for a, b in zip(read[i1:i2], right[j1:j2]) if a.strip() and b.strip()]
    return out


@dataclass
class Lessons:
    sender_aliases: Dict[str, str] = field(default_factory=dict)  # normalized spelling -> canonical sender
    examples: Dict[str, List[Pair]] = field(default_factory=dict)  # field -> (read, correct, times)
    confusions: Dict[str, List[Pair]] = field(default_factory=dict)  # field -> (read char, right char, times)
    missed: Dict[str, int] = field(default_factory=dict)  # field -> times the model said null but a value was there
    invented: Dict[str, int] = field(default_factory=dict)  # field -> times the model gave a value for a blank
    risky: Dict[str, float] = field(default_factory=dict)  # field -> rate of confident-but-wrong readings
    max_lines: int = DEFAULTS["max_lines"]

    def learned_value(self, name: str, raw: Any) -> Optional[str]:
        """The canonical value reviewers always gave to this exact reading, if any."""
        if name == "sender" and isinstance(raw, str):
            return self.sender_aliases.get(normalize_for_match(raw))
        return None

    def prompt_for(self, names: Iterable[str]) -> str:
        lines: List[str] = []
        for n in names:
            for read, right, times in self.confusions.get(n, []):
                lines.append(f"- {n}: you read '{read}' where the correct character was '{right}' "
                             f"({times} corrections). Check every '{read}' against the image.")
            if self.missed.get(n):
                lines.append(f"- {n}: you returned null {self.missed[n]} times when a value was written. "
                             "Look harder before giving up.")
            if self.invented.get(n):
                lines.append(f"- {n}: you returned a value {self.invented[n]} times where the form was blank. "
                             "Return null if nothing is written.")
            for read, right, _ in self.examples.get(n, []):
                lines.append(f"- {n}: where the form said '{read}' the correct value was '{right}'.")
        if not lines:
            return ""
        return ("\n\nLessons from corrections by human reviewers on earlier forms. "
                "Use them to avoid repeating the same mistakes:\n" + "\n".join(lines[:self.max_lines]))

    def summary(self) -> Dict[str, Any]:
        return {
            "sender_aliases": [{"spelling": k, "sender": v} for k, v in sorted(self.sender_aliases.items())],
            "confusions": {n: [{"read": a, "correct": b, "times": c} for a, b, c in v]
                           for n, v in self.confusions.items()},
            "examples": {n: [{"read": a, "correct": b, "times": c} for a, b, c in v]
                         for n, v in self.examples.items()},
            "missed": self.missed,
            "invented": self.invented,
            "always_review": self.risky,
        }


def empty_lessons() -> Lessons:
    return Lessons()


def lessons_of(ctx: Any) -> Lessons:
    return getattr(ctx, "lessons", None) or Lessons()


def load_lessons(s: Session, cfg: Optional[Dict[str, Any]], senders_cfg: Dict[str, Any]) -> Lessons:
    cfg = {**DEFAULTS, **(cfg or {})}
    if not cfg["enabled"]:
        return Lessons()
    need = int(cfg["min_confirmations"])
    rows = s.exec(
        select(Correction).join(Form, Form.id == Correction.form_id)
        .where(Form.workflow == APPROVED).order_by(Correction.id.desc()).limit(int(cfg["window"]))
    ).all()
    lessons = Lessons(max_lines=int(cfg["max_lines"]))
    if not rows:
        return lessons

    # sender spellings that were always fixed to the same canonical name, on at least `need` different forms
    seen: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    canonical = set(canonical_names(senders_cfg))
    pair_counts: Dict[str, Counter] = defaultdict(Counter)
    example_counts: Dict[str, Counter] = defaultdict(Counter)
    for c in rows:
        model, raw, right = _load(c.model_value), _load(c.raw_value), _load(c.corrected_value)
        if c.field_name == "sender" and isinstance(raw, str) and isinstance(right, str):
            seen[normalize_for_match(raw)][right].add(c.form_id)
        if model is None and right is not None:
            lessons.missed[c.field_name] = lessons.missed.get(c.field_name, 0) + 1
        elif model is not None and right is None:
            lessons.invented[c.field_name] = lessons.invented.get(c.field_name, 0) + 1
        elif c.field_name in CHAR_FIELDS and isinstance(model, str) and isinstance(right, str):
            for pair in set(char_confusions(model, right)):
                pair_counts[c.field_name][pair] += 1
        if c.field_name in EXAMPLE_FIELDS and model is not None and right is not None:
            read = raw if c.field_name == "sender" and isinstance(raw, str) else model
            if isinstance(read, str) and isinstance(right, str):
                example_counts[c.field_name][(_show(c.field_name, read), _show(c.field_name, right))] += 1

    for spelling, answers in seen.items():
        if len(answers) == 1:
            (answer, forms), = answers.items()
            if len(forms) >= need and answer in canonical:
                lessons.sender_aliases[spelling] = answer
    lessons.missed = {n: k for n, k in lessons.missed.items() if k >= need}
    lessons.invented = {n: k for n, k in lessons.invented.items() if k >= need}
    for n, counter in pair_counts.items():
        lessons.confusions[n] = [(a, b, k) for (a, b), k in counter.most_common(3) if k >= need]
    for n, counter in example_counts.items():
        lessons.examples[n] = [(a, b, k) for (a, b), k in counter.most_common(4) if a != b]

    # fields the model gets wrong while sure of itself, too often to be trusted without a look
    form_ids = s.exec(select(Form.id).where(Form.workflow == APPROVED).order_by(Form.id.desc())
                      .limit(int(cfg["window_forms"]))).all()
    if len(form_ids) >= int(cfg["min_samples"]):
        recent = set(form_ids)
        confident = Counter(c.field_name for c in rows if c.model_level == "ok" and c.form_id in recent)
        for n in FIELD_NAMES:
            rate = confident.get(n, 0) / len(form_ids)
            if rate >= float(cfg["review_rate"]):
                lessons.risky[n] = round(rate, 3)
    return lessons
