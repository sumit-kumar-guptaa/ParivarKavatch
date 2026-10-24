"""Judge JSON parsing, validation, and retry tests."""

from __future__ import annotations

import pytest

from agents.judge import JudgeAgent, JudgeParseError, parse_debrief_output, parse_judge_output
from app import llm
from app.session import create_drill_session

VALID = (
    '{"tactic_used":"fear","response_type":"resisted","risk_score":2,'
    '"reason":"The parent refused to continue."}'
)


def _session():
    state = create_drill_session(
        parent_id=1,
        scenario_id="digital_arrest",
        difficulty="medium",
    )
    state.current_tactic = "fear"
    return state


def test_parses_fenced_json() -> None:
    verdict = parse_judge_output(f"```json\n{VALID}\n```")
    assert verdict.tactic_used == "fear"
    assert verdict.response_type == "resisted"
    assert verdict.risk_score == 2


def test_rejects_out_of_range_risk() -> None:
    with pytest.raises(JudgeParseError):
        parse_judge_output(
            '{"tactic_used":"fear","response_type":"resisted","risk_score":99,'
            '"reason":"bad score"}'
        )


def test_rejects_unknown_response_type() -> None:
    with pytest.raises(JudgeParseError):
        parse_judge_output(
            '{"tactic_used":"fear","response_type":"panicked","risk_score":4,'
            '"reason":"invalid response type"}'
        )


@pytest.mark.asyncio
async def test_retries_once_after_bad_json(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_complete(system, user, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return "I think the parent resisted, but this is not JSON."
        return VALID

    monkeypatch.setattr(llm, "complete", fake_complete)
    verdict = await JudgeAgent().evaluate(_session(), "Main yeh nahi karunga.", "fear")
    assert calls["count"] == 2
    assert verdict.response_type == "resisted"


@pytest.mark.asyncio
async def test_raises_after_two_bad_outputs(monkeypatch) -> None:
    async def fake_complete(system, user, **kwargs):
        return "still not json"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with pytest.raises(JudgeParseError):
        await JudgeAgent().evaluate(_session(), "Hello?", "fear")


def test_debrief_parser_rejects_extra_keys() -> None:
    raw = (
        '{"summary":"ok","score":70,"tactics_that_worked":[],"key_moments":[],'
        '"what_to_do_next":["hang up"],"safety_notes":[],"unexpected":true}'
    )
    with pytest.raises(JudgeParseError):
        parse_debrief_output(raw)
