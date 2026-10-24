"""Per-parent resilience profile: read, update, and weakest-tactic lookup."""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.playbook import TACTICS, TACTIC_LABELS, TACTIC_TIPS
from db.init import db_session
from db.models import get_or_create_profile_row, utcnow

DEFAULT_RESILIENCE = 0.5
MIN_RESILIENCE = 0.05
MAX_RESILIENCE = 0.95

_DELTAS = {
    "resisted": 0.10,
    "hesitated": -0.02,
    "complied": -0.12,
    "leaked_info": -0.20,
}


def default_resilience() -> dict[str, float]:
    """Cold-start profile: every tactic is equally unfamiliar."""
    return {tactic: DEFAULT_RESILIENCE for tactic in TACTICS}


def _load_values(raw: str | None) -> dict[str, float]:
    values = default_resilience()
    try:
        stored = json.loads(raw or "{}")
    except json.JSONDecodeError:
        stored = {}
    if isinstance(stored, dict):
        for tactic in TACTICS:
            try:
                values[tactic] = min(
                    MAX_RESILIENCE,
                    max(MIN_RESILIENCE, float(stored.get(tactic, DEFAULT_RESILIENCE))),
                )
            except (TypeError, ValueError):
                values[tactic] = DEFAULT_RESILIENCE
    return values


def _snapshot(row: Any, values: dict[str, float]) -> dict[str, Any]:
    weakest = weakest_tactic(values)
    ranked = sorted(values.items(), key=lambda item: (item[1], TACTICS.index(item[0])))
    recommendations = [
        {"tactic": tactic, "label": TACTIC_LABELS[tactic], "tip": TACTIC_TIPS[tactic]}
        for tactic, _score in ranked[:2]
    ]
    return {
        "parent_id": row.parent_id,
        "per_tactic_resilience": {tactic: round(values[tactic], 3) for tactic in TACTICS},
        "sessions_count": row.sessions_count,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "weakest_tactic": weakest,
        "weakest_label": TACTIC_LABELS.get(weakest, weakest),
        "recommendations": recommendations,
    }


def get_profile_snapshot(parent_id: int) -> dict[str, Any]:
    """Read a profile, creating the default row on first access."""
    with db_session() as db:
        row = get_or_create_profile_row(db, parent_id)
        return _snapshot(row, _load_values(row.per_tactic_resilience))


def update_profile_from_turns(
    parent_id: int,
    turns: Iterable[Any],
    *,
    increment_sessions: bool = True,
) -> dict[str, Any]:
    """Apply response deltas for every judged parent turn and bump session count."""
    with db_session() as db:
        row = get_or_create_profile_row(db, parent_id)
        values = _load_values(row.per_tactic_resilience)

        for turn in turns:
            if getattr(turn, "speaker", None) != "parent":
                continue
            tactic = getattr(turn, "tactic_tag", None)
            response_type = getattr(turn, "response_type", None)
            if tactic not in values or response_type not in _DELTAS:
                continue
            values[tactic] = min(
                MAX_RESILIENCE,
                max(MIN_RESILIENCE, values[tactic] + _DELTAS[response_type]),
            )

        row.per_tactic_resilience = json.dumps(
            {tactic: round(values[tactic], 4) for tactic in TACTICS}
        )
        if increment_sessions:
            row.sessions_count = int(row.sessions_count or 0) + 1
        row.updated_at = utcnow()
        return _snapshot(row, values)


def weakest_tactic(
    per_tactic_resilience: dict[str, float],
    allowed: Iterable[str] | None = None,
) -> str:
    """Return the lowest-resilience tactic, with stable playbook tie-breaking."""
    pool = [tactic for tactic in (allowed or TACTICS) if tactic in per_tactic_resilience]
    if not pool:
        pool = list(TACTICS)
    return min(
        pool,
        key=lambda tactic: (
            float(per_tactic_resilience.get(tactic, DEFAULT_RESILIENCE)),
            TACTICS.index(tactic),
        ),
    )
