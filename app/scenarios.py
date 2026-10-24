"""Load and validate the synthetic drill scenarios from scenarios/*.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.playbook import TACTICS

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class ScenarioNotFound(ValueError):
    """Raised when a requested scenario id does not exist."""


def _validate(scenario: dict[str, Any], path: Path) -> dict[str, Any]:
    required = ("id", "title", "caller_persona", "tactics", "tactic_lines", "debrief_tips")
    missing = [key for key in required if key not in scenario]
    if missing:
        raise ValueError(f"{path.name} is missing fields: {', '.join(missing)}")
    unknown = [t for t in scenario["tactics"] if t not in TACTICS]
    if unknown:
        raise ValueError(f"{path.name} has unknown tactics: {', '.join(unknown)}")
    if scenario["id"] != path.stem:
        raise ValueError(f"{path.name} id must match its filename")
    return scenario


@lru_cache(maxsize=32)
def load_scenario(scenario_id: str) -> dict[str, Any]:
    """Load one scenario by id. Files are cached for the process lifetime."""
    if not scenario_id or not scenario_id.replace("_", "").isalnum():
        raise ScenarioNotFound(f"Invalid scenario id: {scenario_id!r}")
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise ScenarioNotFound(f"Unknown scenario: {scenario_id}")
    with path.open(encoding="utf-8") as handle:
        return _validate(json.load(handle), path)


@lru_cache(maxsize=1)
def scenario_summaries() -> list[dict[str, Any]]:
    """Return safe metadata for every scenario (used by the frontend)."""
    summaries: list[dict[str, Any]] = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        scenario = load_scenario(path.stem)
        summaries.append(
            {
                "id": scenario["id"],
                "title": scenario["title"],
                "subtitle": scenario.get("subtitle", ""),
                "risk": scenario.get("risk", "high"),
                "tactics": scenario["tactics"],
            }
        )
    return summaries


def scenario_tactics(scenario: dict[str, Any]) -> list[str]:
    """Return tactics available in a scenario, preserving playbook order."""
    allowed = set(scenario.get("tactics") or TACTICS)
    return [tactic for tactic in TACTICS if tactic in allowed]
