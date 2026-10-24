"""Evaluate the deterministic mock scammer against synthetic golden cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import llm


def main() -> int:
    cases = json.loads(
        (Path(__file__).parent.parent / "tests" / "golden_scammer.json").read_text(
            encoding="utf-8"
        )
    )
    passed = 0
    for case in cases:
        scenario = llm.load_scenario(case["scenario_id"])
        response = llm._contextual_mock_scammer_reply(
            scenario,
            tactic=case["tactic"],
            intensity=1,
            parent_text=case["parent_text"],
        ).lower()
        ok = all(term in response for term in case["must_contain"]) and not any(
            term in response for term in case["must_not_contain"]
        )
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {case['name']}: {response}")
    print(f"Golden evaluation: {passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
