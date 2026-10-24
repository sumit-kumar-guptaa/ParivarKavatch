"""Resilience profile update tests."""

from __future__ import annotations

from app.session import TranscriptTurn
from db.init import db_session
from db.models import create_parent
from memory.profile import get_profile_snapshot, update_profile_from_turns


def _parent_id() -> int:
    with db_session() as db:
        parent = create_parent(db, "Test Parent")
        return parent.id


def test_new_profile_is_neutral() -> None:
    parent_id = _parent_id()
    snapshot = get_profile_snapshot(parent_id)
    assert snapshot["sessions_count"] == 0
    assert snapshot["per_tactic_resilience"]["authority"] == 0.5
    assert len(snapshot["per_tactic_resilience"]) == 8


def test_profile_update_moves_resilience_and_counts_session() -> None:
    parent_id = _parent_id()
    turns = [
        TranscriptTurn(
            index=0,
            speaker="parent",
            text="Nahi.",
            tactic_tag="authority",
            response_type="resisted",
            risk_score=2,
        ),
        TranscriptTurn(
            index=1,
            speaker="parent",
            text="Theek hai.",
            tactic_tag="fear",
            response_type="complied",
            risk_score=7,
        ),
    ]
    snapshot = update_profile_from_turns(parent_id, turns)
    assert snapshot["sessions_count"] == 1
    assert snapshot["per_tactic_resilience"]["authority"] == 0.6
    assert snapshot["per_tactic_resilience"]["fear"] == 0.38
    assert snapshot["weakest_tactic"] == "fear"


def test_profile_accumulates_across_drills() -> None:
    parent_id = _parent_id()
    turn = TranscriptTurn(
        index=0,
        speaker="parent",
        text="Mujhe verify karna hai.",
        tactic_tag="urgency",
        response_type="hesitated",
        risk_score=5,
    )
    first = update_profile_from_turns(parent_id, [turn])
    second = update_profile_from_turns(parent_id, [turn])
    assert first["sessions_count"] == 1
    assert second["sessions_count"] == 2
    assert second["per_tactic_resilience"]["urgency"] == 0.46


def test_unjudged_turns_are_ignored() -> None:
    parent_id = _parent_id()
    turns = [
        TranscriptTurn(index=0, speaker="scammer", text="Hello", tactic_tag="fear"),
        TranscriptTurn(index=1, speaker="parent", text="Hmm"),
    ]
    snapshot = update_profile_from_turns(parent_id, turns)
    assert snapshot["sessions_count"] == 1
    assert all(value == 0.5 for value in snapshot["per_tactic_resilience"].values())
