"""Phase-2 style terminal drill: no audio, no database, mocks by default.

Usage:
    python scripts/text_drill.py --scenario digital_arrest --difficulty medium
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.guard import (  # noqa: E402
    GUARD_MESSAGE,
    redact_sensitive,
    scan_parent_text,
    scan_scammer_line,
)
from agents.judge import JudgeAgent, JudgeParseError, fallback_debrief  # noqa: E402
from agents.scammer import ScammerAgent  # noqa: E402
from app.config import settings  # noqa: E402
from app.playbook import TACTIC_LABELS  # noqa: E402
from app.scenarios import load_scenario, scenario_summaries  # noqa: E402
from app.session import DrillSession  # noqa: E402
from memory.profile import default_resilience  # noqa: E402


async def run_drill(scenario_id: str, difficulty: str) -> None:
    scenario = load_scenario(scenario_id)
    state = DrillSession(
        id="terminal-drill",
        parent_id=0,
        scenario_id=scenario_id,
        difficulty=difficulty,  # type: ignore[arg-type]
        scenario=scenario,
        max_turns=settings.max_turns_for(difficulty),
    )
    profile = default_resilience()
    scammer = ScammerAgent()
    judge = JudgeAgent()

    print(f"\n=== {scenario['title']} | {difficulty.upper()} | mocks={settings.use_mocks} ===\n")
    print("Type your reply as the parent. Type /quit to end early.\n")

    opening = await scammer.opening(state, profile)
    opening_guard = scan_scammer_line(opening.text)
    opening_text = opening_guard.text if opening_guard.activated else opening.text
    if opening_guard.activated:
        state.add_guard_event(
            kind=opening_guard.kind,
            reason=opening_guard.reason,
            excerpt=redact_sensitive(opening.text),
        )
    state.current_tactic = opening.tactic
    state.add_turn("guard" if opening_guard.activated else "scammer", opening_text, tactic_tag=opening.tactic)
    print(f"CALLER [{TACTIC_LABELS[opening.tactic]}]: {opening_text}\n")

    while state.turn_count < state.max_turns:
        try:
            parent_text = (await asyncio.to_thread(input, "PARENT: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not parent_text:
            continue
        if parent_text.lower() in {"/quit", "quit", "exit"}:
            break

        state.turn_count += 1
        parent_scan = scan_parent_text(parent_text)
        if parent_scan.injection_detected:
            state.add_guard_event(
                kind="prompt_injection",
                reason="Instruction-like text ignored.",
                excerpt=parent_scan.excerpt,
            )
            print("GUARD: Instruction-like text was treated as untrusted and ignored.")
        if parent_scan.sensitive_data_detected:
            state.add_guard_event(
                kind="sensitive_data_shared",
                reason=parent_scan.reason,
                excerpt=parent_scan.excerpt,
            )

        judge_result, scammer_result = await asyncio.gather(
            judge.evaluate(state, parent_text, state.current_tactic),
            scammer.respond(state, profile, parent_text, state.last_verdict),
            return_exceptions=True,
        )
        if isinstance(scammer_result, Exception):
            print(f"CALLER ERROR: {scammer_result}")
            break
        line = scammer_result
        if isinstance(judge_result, Exception):
            print(f"JUDGE FALLBACK: {judge_result}")
            from agents.judge import JudgeVerdict

            verdict = JudgeVerdict(
                tactic_used=state.current_tactic or "authority",
                response_type="leaked_info" if parent_scan.sensitive_data_detected else "hesitated",
                risk_score=10 if parent_scan.sensitive_data_detected else 5,
                reason="Conservative fallback after invalid judge output.",
            )
        else:
            verdict = judge_result

        safe_reason = redact_sensitive(verdict.reason)
        verdict_payload = verdict.model_dump(mode="json")
        verdict_payload["reason"] = safe_reason
        state.last_verdict = verdict_payload
        state.add_tactic_event(
            turn=state.turn_count,
            tactic=verdict.tactic_used,
            response_type=verdict.response_type,
            risk_score=verdict.risk_score,
            reason=safe_reason,
        )
        stored_parent_text = (
            redact_sensitive(parent_text) if parent_scan.sensitive_data_detected else parent_text
        )
        state.add_turn(
            "parent",
            stored_parent_text,
            tactic_tag=verdict.tactic_used,
            response_type=verdict.response_type,
            risk_score=verdict.risk_score,
        )
        print(
            f"JUDGE: {TACTIC_LABELS.get(verdict.tactic_used, verdict.tactic_used)} | "
            f"{verdict.response_type} | risk {verdict.risk_score}/10 | {safe_reason}"
        )

        outbound = scan_scammer_line(line.text)
        guard_break = parent_scan.sensitive_data_detected or outbound.activated
        final_text = GUARD_MESSAGE if guard_break else line.text
        if outbound.activated:
            state.add_guard_event(
                kind=outbound.kind,
                reason=outbound.reason,
                excerpt=redact_sensitive(line.text),
            )
        state.current_tactic = line.tactic
        state.add_turn("guard" if guard_break else "scammer", final_text, tactic_tag=line.tactic)
        speaker = "GUARD" if guard_break else f"CALLER [{TACTIC_LABELS[line.tactic]}]"
        print(f"{speaker}: {final_text}\n")

    try:
        debrief = await judge.make_debrief(state)
    except JudgeParseError as exc:
        print(f"DEBRIEF FALLBACK: {exc}")
        debrief = fallback_debrief(state)

    print("=== DEBRIEF ===")
    print(f"Score: {debrief.score}/100")
    print(debrief.summary)
    print("\nKey moments:")
    for moment in debrief.key_moments:
        print(f"  Turn {moment.turn}: {moment.tactic} -> {moment.response_type} ({moment.note})")
    print("\nPractise next:")
    for tip in debrief.what_to_do_next:
        print(f"  - {tip}")
    print("\nNote: this terminal drill does not persist the profile. Use the web app for memory.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a text-only Parivar Kavach drill.")
    parser.add_argument(
        "--scenario",
        default="digital_arrest",
        choices=[summary["id"] for summary in scenario_summaries()],
    )
    parser.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    args = parser.parse_args()
    asyncio.run(run_drill(args.scenario, args.difficulty))


if __name__ == "__main__":
    main()
