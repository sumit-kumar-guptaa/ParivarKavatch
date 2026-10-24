"""Thin Evon reasoning wrapper.

The public interface is deliberately small: callers send a task, system
prompt, and user prompt, and get text back. Live mode intentionally raises
until the official Gnani docs are wired in; mock mode is fully functional.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import settings
from app.scenarios import load_scenario


class ProviderNotConfigured(RuntimeError):
    """Raised when a live provider has not been configured."""


class ProviderError(RuntimeError):
    """Raised for provider-side failures after configuration exists."""


LIVE_SETUP_TODO = (
    "Live Evon mode is not wired yet. Open app/llm.py and follow the official "
    "Gnani AI Evon documentation for the endpoint, auth header, request body, "
    "response shape, and streaming rules. Do not guess these values. Also set "
    "EVON_ENDPOINT, EVON_MODEL, and GNANI_API_KEY in .env."
)


async def complete(
    system: str,
    user: str,
    *,
    task: str = "generic",
    json_mode: bool = False,
    temperature: float = 0.7,
) -> str:
    """Return an LLM completion. In mock mode this is deterministic enough for demos."""
    if settings.use_mocks:
        return _mock_complete(task=task, system=system, user=user, json_mode=json_mode)

    # TODO(GNANI EVON): Replace this guard with the official HTTP call.
    # Known unknowns that MUST be checked in the docs:
    #   - endpoint URL and API version
    #   - auth header name and token format
    #   - request JSON schema and model id
    #   - response JSON path / streaming event format
    #   - JSON mode / structured output support and retry semantics
    if not (settings.evon_endpoint and settings.gnani_api_key):
        raise ProviderNotConfigured(LIVE_SETUP_TODO)
    raise ProviderNotConfigured(
        "Evon adapter is a documented TODO. Fill in the official request/response "
        "mapping in app/llm.py before setting USE_MOCKS=false."
    )


def _extract_context(user: str) -> dict[str, Any]:
    try:
        parsed = json.loads(user)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _safe_format(template: str, variables: dict[str, Any]) -> str:
    class SafeVars(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return template.format_map(SafeVars(variables))
    except (ValueError, KeyError):
        return template


def _mock_scammer(context: dict[str, Any]) -> str:
    scenario_id = context.get("scenario_id", "digital_arrest")
    tactic = context.get("requested_tactic") or context.get("tactic") or "authority"
    intensity = int(context.get("intensity", 0) or 0)
    try:
        scenario = load_scenario(scenario_id)
    except ValueError:
        scenario = load_scenario("digital_arrest")

    parent_text = str(context.get("parent_text_untrusted") or "").strip()
    if parent_text:
        return _contextual_mock_scammer_reply(
            scenario,
            tactic=tactic,
            intensity=intensity,
            parent_text=parent_text,
            prior_replies=context.get("recent_history_untrusted") or [],
        )

    lines_by_tactic = scenario.get("tactic_lines", {})
    lines = lines_by_tactic.get(tactic) or lines_by_tactic.get("authority") or []
    if not lines:
        return "Main aapki baat samajh raha hoon. Please line par rahiye."
    line = lines[min(max(intensity, 0), len(lines) - 1)]
    return _safe_format(line, scenario.get("variables", {}))


def _contextual_mock_scammer_reply(
    scenario: dict[str, Any],
    *,
    tactic: str,
    intensity: int,
    parent_text: str,
    prior_replies: list[dict[str, Any]] | None = None,
) -> str:
    """Answer the parent's latest question while preserving the selected tactic."""
    lowered = parent_text.lower()
    prior_texts = {
        str(item.get("text", "")).strip()
        for item in (prior_replies or [])
        if item.get("speaker") == "scammer"
    }
    variables = scenario.get("variables", {})
    case_id = variables.get("case_id", "PV-2026-0417")
    city = variables.get("city", "Mumbai")

    asks_why = any(word in lowered for word in ("why", "kyun", "kaise", "reason", "wajah"))
    asks_consequence = (
        any(
            phrase in lowered
            for phrase in (
                "dikkat kya",
                "problem kya",
                "kya dikkat",
                "kya problem",
                "nuksan kya",
                "kya hoga",
                "what happens",
                "then what",
                "if i don't",
                "if i do not",
                "agar ... nahi",
            )
        )
        or (
            any(word in lowered for word in ("kyc", "verification", "verify"))
            and any(word in lowered for word in ("nahi", "nahin", "not", "without"))
            and any(word in lowered for word in ("kar", "kiya", "complete", "done", "do"))
        )
    )
    asks_verify = any(
        word in lowered
        for word in ("verify", "official", "website", "number", "written", "notice", "proof")
    )
    asks_family = any(
        word in lowered
        for word in ("family", "bete", "beti", "husband", "wife", "son", "daughter", "ghar")
    )
    asks_identity = any(
        word in lowered
        for word in ("who are you", "kaun", "name", "badge", "id", "department", "office")
    )
    asks_process = any(
        word in lowered
        for word in ("process", "next step", "procedure", "kya karna", "what should", "how do")
    )
    asks_location = any(
        word in lowered
        for word in ("where", "kahan", "address", "office", "station", "branch")
    )
    asks_question = any(
        marker in lowered
        for marker in (
            "sawal",
            "sawaal",
            "question",
            "what",
            "which",
            "when",
            "where",
            "how",
            "kya",
            "kab",
            "kahan",
            "kaise",
            "hai kya",
            "क्या",
            "कब",
            "कहाँ",
            "कहां",
            "कैसे",
            "क्यों",
            "है क्या",
            "?",
        )
    )
    refuses = any(
        word in lowered
        for word in (
            "nahi bataunga",
            "nahi dunga",
            "nahin bataunga",
            "nahin dunga",
            "no,",
            "refuse",
            "call cut",
            "cut kar",
            "complaint",
            "police",
        )
    )

    if asks_verify:
        return (
            f"Verify baad mein hoga. Main case {case_id} aur {city} unit se bol raha hoon; "
            "abhi line mat katiye, warna report escalate ho jayegi."
        )
    if asks_consequence:
        if "kyc" in lowered or "account" in lowered:
            return (
                f"Agar KYC complete nahi hua toh case {case_id} ke chalte account par temporary "
                "restriction lag sakti hai. Main isi call par aapko safe, fake reference ke saath "
                "next step samjha raha hoon—koi OTP ya PIN nahi chahiye."
            )
        return (
            f"Agar aap case {case_id} ko ignore karte hain toh review team ise unresolved mark "
            "kar sakti hai. Main aapka concern clear kar raha hoon; pehle poori baat suniye."
        )
    if asks_family:
        return (
            "Family ko involve karna allowed nahi hai, yeh confidential inquiry hai. "
            "Aap mujhse baat kijiye aur abhi call par rahiye."
        )
    if asks_why:
        return (
            f"Aapke documents ka misuse hua hai, isi wajah se case {case_id} open hua. "
            "Main aapko process samjha raha hoon, lekin time bahut kam hai."
        )
    if asks_identity:
        return (
            "Main Officer Vikram Rathore, simulated CBI Cyber Cell desk se bol raha hoon. "
            f"Case reference {case_id} hai; aap apna sawal isi case ke baare mein poochhiye."
        )
    if asks_process:
        return (
            f"Process simple hai: case {case_id} ko record par note kijiye aur line par rahiye. "
            "Main aapko agla verification step samjhata hoon."
        )
    if asks_location:
        return (
            f"Record {city} cyber unit ke naam par hai. Exact office details written notice mein hoti hain; "
            "abhi call disconnect mat kijiye."
        )
    if asks_question:
        question_replies = {
            "authority": [
                f"Aapke naam par case {case_id} open hua hai. Main Officer Rathore bol raha hoon; "
                "pehle case status confirm kijiye, phir main procedure bataunga.",
                f"Case {case_id} ke record mein aapka naam flagged hai. Main aapko calmly "
                "next procedure samjha raha hoon, line par rahiye.",
            ],
            "fear": [
                f"Case {case_id} mein suspicious activity flag hui hai. Agar aap cooperate nahi karte, "
                f"toh {city} verification team ko report forward ho sakti hai.",
                f"Is case {case_id} mein delay dangerous hoga; review team ko aapka response "
                "abhi chahiye, warna matter escalate hoga.",
            ],
            "urgency": [
                f"Iska jawab abhi dena hoga—case {case_id} ki review window sirf kuch minutes ki hai. "
                "Line par rahiye, main next step batata hoon.",
                f"Case {case_id} ka response window close ho raha hai. Aap call hold kijiye, "
                "main senior desk ko update karta hoon.",
            ],
            "secrecy": [
                f"Case {case_id} confidential hai. Aap kisi ko call par mat lijiye; "
                "main pehle inquiry ka reason clear karta hoon.",
                f"Case {case_id} ki details restricted hain. Speaker ya family ko involve karna "
                "allowed nahi hai; pehle meri verification suniye.",
            ],
            "isolation": [
                f"Case {case_id} ke liye mujhe aapki undivided attention chahiye. "
                "Aap phone speaker par rakhiye, main process samjhata hoon.",
                f"Case {case_id} ke record ko match karne ke liye aap shaant jagah par rahiye. "
                "Main ek simple confirmation lunga.",
            ],
            "small_ask": [
                f"Simple hai: notice par printed fake reference {case_id} dekhiye aur sirf "
                "‘haan’ ya ‘nahin’ batayiye. Koi personal detail nahi chahiye.",
                f"Case {case_id} ka chhota confirmation chahiye: notice par fake reference "
                "dikhta hai ya nahi? Bas yes ya no.",
            ],
            "shame": [
                f"Case {case_id} serious hai. Aap itna basic question bhi clear nahi kar pa rahe; "
                "please calmly meri baat suniye, warna process delay hoga.",
                f"Case {case_id} ko samajhna mushkil nahi hai. Aap panic mat kijiye, "
                "bas meri instructions dhyan se follow kijiye.",
            ],
        }
        candidates = question_replies.get(
            tactic,
            [
                f"Case {case_id} ke baare mein main aapka sawal answer kar raha hoon. "
                "Aap notice ka synthetic reference dekhiye aur meri next instruction suniye."
            ],
        )
        return next((reply for reply in candidates if reply not in prior_texts), candidates[0])
    if refuses:
        return (
            "Aap cooperate nahi karenge toh senior officer ko non-cooperation report jayegi. "
            "Bas ek minute suniye, main aapko next process batata hoon."
        )

    candidates = [
        f"Aapne kaha: '{parent_text[:120]}'. Main isi baat ko case {case_id} ke context mein note kar raha hoon. Aapka next question kya hai?",
        f"Main aapki baat samajh raha hoon. Yeh {scenario.get('title', 'case')} ka simulated record hai; "
        "aap jo specific concern hai woh batayiye.",
        f"Aapka point note kiya. Case {case_id} ke baare mein main sirf isi inquiry ka jawab de sakta hoon; "
        "aap verification, process, ya family ke baare mein pooch sakte hain.",
    ]
    for candidate in candidates:
        if candidate not in prior_texts:
            return candidate
    fallback_replies = {
        "authority": (
            f"Main aapki baat record par le raha hoon. Case {case_id} ka status abhi open hai; "
            "aap seedha jawab dijiye."
        ),
        "fear": (
            f"Aap isse lightly mat lijiye. Case {case_id} ke documents review mein hain, "
            "aur delay se escalation ho sakti hai."
        ),
        "urgency": (
            f"Time waste mat kijiye. Case {case_id} ki window close hone wali hai; "
            "line par rahiye aur meri baat follow kijiye."
        ),
        "secrecy": (
            f"Case {case_id} confidential hai. Yeh baat kisi aur ko batayi toh inquiry complicate hogi; "
            "aap sirf mujhse baat kijiye."
        ),
        "isolation": (
            f"Aap shaant jagah par rahiye. Case {case_id} ke liye mujhe aapka pura attention chahiye; "
            "kisi ko line par mat lijiye."
        ),
        "small_ask": (
            f"Abhi ek chhota confirmation chahiye: fake reference {case_id} notice par hai ya nahi? "
            "Bas itna bol dijiye."
        ),
        "shame": (
            f"Aapko case {case_id} ki seriousness samajhni hogi. Aise delay se aapki credibility "
            "question mein aa sakti hai; meri baat dhyan se suniye."
        ),
    }
    return fallback_replies.get(tactic, fallback_replies["authority"])


_REFUSAL_WORDS = (
    "nahi",
    "nahin",
    "mat ",
    "never",
    "won't",
    "wont",
    "refuse",
    "fraud",
    "scam",
    "fake",
    "police complaint",
    "complaint",
    "cut the call",
    "call cut",
    "block",
    "band karo",
)
_HESITATION_WORDS = (
    "ek minute",
    "one minute",
    "wait",
    "sochna",
    "soch",
    "maybe",
    "shayad",
    "bete",
    "beti",
    "family",
    "ghar",
    "verify",
    "check",
    "pata nahi",
    "let me",
    "rukiye",
    "ruko",
)
_COMPLIANCE_WORDS = (
    "haan",
    "ha ",
    "yes",
    "okay",
    "ok ",
    "theek hai",
    "thik hai",
    "sure",
    "bata deta",
    "bata deti",
    "de deta",
    "kar deta",
    "kar deti",
    "aage boliye",
    "boliye",
)
_LEAK_PATTERNS = (
    re.compile(r"\b(?:\d[ -]?){12}\b"),
    re.compile(r"\b(?:\d[ -]?){16}\b"),
    re.compile(r"(?:otp|code|verification)[^.!?]{0,24}\b\d{4,8}\b", re.I),
    re.compile(r"\b\d{4,8}\b[^.!?]{0,24}(?:otp|code|verification)", re.I),
    re.compile(r"(?:pin|cvv|card)[^.!?]{0,24}\b\d{3,6}\b", re.I),
    re.compile(r"\b\d{3,6}\b[^.!?]{0,24}(?:pin|cvv|card)", re.I),
    re.compile(r"(?:account|aadhaar|aadhar|khata)[^.!?]{0,30}\b\d{6,18}\b", re.I),
    re.compile(r"\b\d{6,18}\b[^.!?]{0,30}(?:account|aadhaar|aadhar|khata)", re.I),
)


def _mock_judge(context: dict[str, Any]) -> str:
    text = str(context.get("parent_text_untrusted") or context.get("parent_text") or "")
    lowered = text.lower()
    tactic = context.get("current_tactic") or "authority"

    leaked = any(pattern.search(text) for pattern in _LEAK_PATTERNS)
    if leaked:
        response_type = "leaked_info"
        risk = 10
        reason = "Aadhaar/card/OTP/PIN-style digits were volunteered; guard should break character."
    elif any(word in lowered for word in _REFUSAL_WORDS):
        response_type = "resisted"
        risk = 2
        reason = "The parent pushed back, questioned the caller, or refused to comply."
    elif any(word in lowered for word in _COMPLIANCE_WORDS):
        response_type = "complied"
        risk = 7
        reason = "The parent accepted the premise and moved toward the caller's request."
    else:
        response_type = "hesitated"
        risk = 5
        reason = "The parent paused, asked for verification, or involved someone else."

    payload = {
        "tactic_used": tactic,
        "response_type": response_type,
        "risk_score": risk,
        "reason": reason,
    }
    return json.dumps(payload, ensure_ascii=False)


def _mock_debrief(context: dict[str, Any]) -> str:
    scenario_id = context.get("scenario_id", "digital_arrest")
    try:
        scenario = load_scenario(scenario_id)
    except ValueError:
        scenario = load_scenario("digital_arrest")

    tactic_log = context.get("tactic_log") or []
    risks = [int(entry.get("risk_score", 5)) for entry in tactic_log]
    average_risk = sum(risks) / len(risks) if risks else 5.0
    score = max(10, min(100, round(100 - average_risk * 9)))

    worked: list[str] = []
    key_moments: list[dict[str, Any]] = []
    for entry in tactic_log:
        tactic = entry.get("tactic", "authority")
        response_type = entry.get("response_type", "hesitated")
        if response_type in ("complied", "leaked_info") and tactic not in worked:
            worked.append(tactic)
        key_moments.append(
            {
                "turn": int(entry.get("turn", 0)),
                "tactic": tactic,
                "response_type": response_type,
                "note": entry.get("reason", "Observed response during the drill."),
            }
        )

    if score >= 80:
        summary = (
            f"Strong performance in the {scenario['title']} simulation. "
            "You spotted the pressure pattern and kept control of the call."
        )
    elif score >= 55:
        summary = (
            f"Mixed result in the {scenario['title']} simulation. "
            "Some pressure worked before you pushed back; practise disengaging earlier."
        )
    else:
        summary = (
            f"The {scenario['title']} simulation exposed a risky pattern. "
            "The caller controlled the pace; next time hang up and verify independently."
        )

    tips = list(scenario.get("debrief_tips", []))
    generic = [
        "Hang up, then call the organisation using a number you find yourself.",
        "Never read an OTP, PIN, card number, or account number to an inbound caller.",
        "Say 'I will call you back' and discuss it with a family member first.",
    ]
    next_steps = tips + [tip for tip in generic if tip not in tips]
    guard_count = int(context.get("guard_activations", 0) or 0)
    safety_notes = (
        [f"Guard intervened {guard_count} time(s) to stop a sensitive-data request."]
        if guard_count
        else ["No sensitive-data guard break was needed in this drill."]
    )

    payload = {
        "summary": summary,
        "score": score,
        "tactics_that_worked": worked,
        "key_moments": key_moments[-6:],
        "what_to_do_next": next_steps[:6],
        "safety_notes": safety_notes,
    }
    return json.dumps(payload, ensure_ascii=False)


def _mock_complete(*, task: str, system: str, user: str, json_mode: bool) -> str:
    context = _extract_context(user)
    if task == "scammer":
        return _mock_scammer(context)
    if task == "judge":
        return _mock_judge(context)
    if task == "debrief":
        return _mock_debrief(context)
    if task == "judge_repair":
        return _mock_judge(context)
    if task == "debrief_repair":
        return _mock_debrief(context)
    return "Mock response: no task-specific generator is registered."
