"""Scenario catalogue integrity tests."""

from app.playbook import TACTICS
from app.scenarios import load_scenario, scenario_summaries


def test_all_five_scenarios_load() -> None:
    ids = {summary["id"] for summary in scenario_summaries()}
    assert ids == {
        "digital_arrest",
        "bank_kyc",
        "courier_parcel",
        "refund_prize",
        "relative_trouble",
    }


def test_every_scenario_has_safe_tactic_lines() -> None:
    for summary in scenario_summaries():
        scenario = load_scenario(summary["id"])
        assert scenario["tactics"]
        for tactic in scenario["tactics"]:
            assert tactic in TACTICS
            assert scenario["tactic_lines"].get(tactic)
        assert scenario["debrief_tips"]
