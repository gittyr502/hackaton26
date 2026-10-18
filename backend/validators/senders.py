"""Matching a sender against the closed list in senders.yaml."""
import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[\"'״׳`.,\-()]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_names(cfg: Dict[str, Any]) -> List[str]:
    return [s["name"] for s in cfg.get("senders", [])]


def match_sender(value: str, cfg: Dict[str, Any]) -> Tuple[Optional[str], float, bool]:
    """Return (canonical name or None, score 0-100, exact).

    exact=True when the value equals a name/alias after normalization.
    Below the configured threshold the canonical name is None.
    """
    if not value:
        return None, 0.0, False
    v = _norm(value)
    best_name, best_score = None, 0.0
    for s in cfg.get("senders", []):
        for cand in [s["name"], *s.get("aliases", [])]:
            c = _norm(cand)
            if v == c:
                return s["name"], 100.0, True
            score = max(fuzz.ratio(v, c), fuzz.token_set_ratio(v, c) if len(v) >= 4 else 0)
            if score > best_score:
                best_name, best_score = s["name"], score
    if best_score >= cfg.get("match_threshold", 85):
        return best_name, best_score, False
    return None, best_score, False


def is_canonical(value: str, cfg: Dict[str, Any]) -> bool:
    return value in canonical_names(cfg)
