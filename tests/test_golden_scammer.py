from __future__ import annotations

import json
from pathlib import Path

from app import llm


def test_mock_scammer_golden_dataset() -> None:
    cases = json.loads(
        (Path(__file__).parent / "golden_scammer.json").read_text(encoding="utf-8")
    )
    failures: list[str] = []
    for case in cases:
        scenario = llm.load_scenario(case["scenario_id"])
        response = llm._contextual_mock_scammer_reply(
            scenario,
            tactic=case["tactic"],
            intensity=1,
            parent_text=case["parent_text"],
        ).lower()
        missing = [term for term in case["must_contain"] if term not in response]
        unsafe = [term for term in case["must_not_contain"] if term in response]
        if missing or unsafe:
            failures.append(f"{case['name']}: missing={missing}, unsafe={unsafe}, response={response}")
    assert not failures, "\n".join(failures)


def test_mock_scammer_changes_reply_for_different_questions() -> None:
    scenario = llm.load_scenario("digital_arrest")
    verification = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="fear",
        intensity=1,
        parent_text="Aapka official website aur written notice kahan hai?",
    )
    family = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="secrecy",
        intensity=1,
        parent_text="Main apni family ko speaker par bula raha hoon.",
    )
    assert verification != family
    assert "website" not in family.lower()
    assert "family" in family.lower()


def test_mock_scammer_stays_relevant_for_unmatched_text() -> None:
    scenario = llm.load_scenario("digital_arrest")
    response = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="authority",
        intensity=0,
        parent_text="Mujhe samajh nahi aa raha, aap seedha bataiye.",
    )
    assert "case" in response.lower() or "simulated" in response.lower()


def test_mock_scammer_answers_sawal_kya_hai() -> None:
    scenario = llm.load_scenario("digital_arrest")
    response = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="fear",
        intensity=1,
        parent_text="sawal kya hai",
    )
    assert "case" in response.lower()


def test_mock_scammer_answers_devanagari_question_without_echoing_it() -> None:
    scenario = llm.load_scenario("digital_arrest")
    parent_text = "क्या आठ बजे का क्लेम वीडियो पहुंच जाए तो क्या है?"
    response = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="urgency",
        intensity=1,
        parent_text=parent_text,
    )
    assert "case" in response.lower()
    assert "personal details" not in response.lower()
    assert parent_text not in response


def test_mock_scammer_answers_kyc_consequence_question() -> None:
    scenario = llm.load_scenario("bank_kyc")
    response = llm._contextual_mock_scammer_reply(
        scenario,
        tactic="small_ask",
        intensity=1,
        parent_text="agar mein kyc nahi kiya toh dikkat kya hai",
    ).lower()
    assert "kyc" in response
    assert "account" in response
    assert "otp" in response or "pin" in response
    assert "printed fake reference" not in response
