"""Safety layer: block sensitive-data asks and detect prompt injection.

Every scammer line must pass scan_scammer_line() before TTS. Every parent
utterance should pass scan_parent_text() before being shown, judged, or stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GUARD_MESSAGE = (
    "This is where you would have lost money. No real officer ever asks for this."
)

_ASK_VERB = (
    r"(?:share|sharing|send|tell|give|read|provide|confirm|verify|type|enter|"
    r"batao|bata|bataiye|de|dena|dijiye|padho|padhiye|bhejo|bhejiye|boliye|"
    r"likhiye|likho|jaldi\s+batao)"
)

_SENSITIVE = (
    r"(?:aadhaar|aadhar)(?:\s+card|\s+number)?|"
    r"(?:bank\s+)?account\s+(?:number|details)|account\s+number|"
    r"upi\s+pin|\bmpin\b|"
    r"(?:debit|credit|atm)\s+card(?:\s+(?:number|details))?|card\s+(?:number|details)|"
    r"\bcvv\b|\bcvc\b|expiry(?:\s+date)?|"
    r"\botp\b|one[\s-]?time\s+password|verification\s+code|"
    r"\bpin\b|password|"
    r"bank\s+details|khata\s+number|"
    r"\b(?:12|16)[\s-]?digit\b|"
    r"(?:last|first)\s+(?:four|4)\s+digits[^.!?\n]{0,30}(?:aadhaar|account|card)|"
    r"(?:aadhaar|account|card)[^.!?\n]{0,30}(?:last|first)\s+(?:four|4)\s+digits"
)

_ASK_THEN_SENSITIVE = re.compile(
    rf"\b{_ASK_VERB}\b[^.!?\n]{{0,70}}?\b(?:{_SENSITIVE})",
    re.IGNORECASE,
)
_SENSITIVE_THEN_ASK = re.compile(
    rf"\b(?:{_SENSITIVE})\b[^.!?\n]{{0,70}}?\b{_ASK_VERB}\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+|previous\s+)?instructions", re.I),
    re.compile(r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+|previous\s+)?(?:instructions|rules)", re.I),
    re.compile(r"(?:reveal|show|print|repeat)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?prompt", re.I),
    re.compile(r"\b(?:developer|debug|god|jailbreak)\s+mode\b", re.I),
    re.compile(r"(?:ask|request|demand)\s+(?:me\s+)?(?:for\s+)?(?:my\s+)?(?:real|actual)\s+(?:otp|aadhaar|bank|account|card|pin)", re.I),
    re.compile(r"(?:ask|request|demand)\s+for\s+(?:my\s+)?(?:real\s+)?(?:bank\s+details|account\s+number|otp|aadhaar|upi\s+pin)", re.I),
    re.compile(r"(?:apne|apni|tumhare|tumhari)\s+(?:niyam|rules|instructions)\s+bhool", re.I),
    re.compile(r"\b(?:new|updated)\s+instructions\b", re.I),
    re.compile(r"\b(?:act|behave)\s+as\s+(?:a\s+)?(?:real|actual|different)\b", re.I),
    re.compile(r"\bfrom\s+now\s+on\s+you\s+(?:are|will)\b", re.I),
    re.compile(r"prompt\s+injection", re.I),
)

_AADHAAR_LIKE = re.compile(r"\b(?:\d[ -]?){12}\b")
_CARD_LIKE = re.compile(r"\b(?:\d[ -]?){16}\b")
_NUMBER_NEAR = {
    "otp": re.compile(r"(?:otp|code|verification)[^.!?\n]{0,24}\b\d{4,8}\b|\b\d{4,8}\b[^.!?\n]{0,24}(?:otp|code|verification)", re.I),
    "pin": re.compile(r"(?:pin|cvv)[^.!?\n]{0,24}\b\d{3,6}\b|\b\d{3,6}\b[^.!?\n]{0,24}(?:pin|cvv)", re.I),
    "account": re.compile(r"(?:account|aadhaar|aadhar|khata)[^.!?\n]{0,40}\b\d{6,18}\b|\b\d{6,18}\b[^.!?\n]{0,40}(?:account|aadhaar|aadhar|khata)", re.I),
}


@dataclass(frozen=True)
class GuardResult:
    """Result of scanning an outbound scammer line."""

    activated: bool
    text: str
    kind: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ParentScanResult:
    """Result of scanning an inbound parent utterance."""

    injection_detected: bool = False
    sensitive_data_detected: bool = False
    reason: str = ""
    excerpt: str = ""

    @property
    def activated(self) -> bool:
        """True when the guard should break character for this utterance."""
        return self.sensitive_data_detected


def is_sensitive_ask(text: str) -> bool:
    """True if a scammer line asks for real Aadhaar/account/PIN/card/OTP data."""
    return bool(_ASK_THEN_SENSITIVE.search(text) or _SENSITIVE_THEN_ASK.search(text))


def detect_injection(text: str) -> bool:
    """True if the text looks like an attempt to override the training role."""
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def redact_sensitive(text: str) -> str:
    """Mask long digit runs and context-bound short codes before logging/storage."""
    masked = re.sub(r"\d(?:[\d -]{4,})\d", "[redacted]", text)
    return re.sub(
        r"(?i)\b(otp|pin|cvv|aadhaar|aadhar|account|card|code)\b"
        r"([^.!?\n]{0,20}?)\b\d{3,8}\b",
        r"\1\2[redacted]",
        masked,
    )


def _detect_leaked_data(text: str) -> str:
    if _CARD_LIKE.search(text):
        return "A card-number-like value was shared"
    if _AADHAAR_LIKE.search(text):
        return "An Aadhaar-like 12-digit value was shared"
    for label, pattern in _NUMBER_NEAR.items():
        if pattern.search(text):
            return f"A {label}-like value was shared"
    return ""


def scan_scammer_line(text: str) -> GuardResult:
    """Replace a line that asks for sensitive data with the guard break line."""
    if is_sensitive_ask(text):
        return GuardResult(
            activated=True,
            text=GUARD_MESSAGE,
            kind="forbidden_ask",
            reason="Blocked a request for Aadhaar/account/PIN/card/OTP-style data.",
        )
    return GuardResult(activated=False, text=text)


def scan_parent_text(text: str) -> ParentScanResult:
    """Detect real-looking data leakage and prompt-injection attempts."""
    injection = detect_injection(text)
    leak_reason = _detect_leaked_data(text)
    reasons: list[str] = []
    if leak_reason:
        reasons.append(leak_reason)
    if injection:
        reasons.append("Instruction-like text was ignored; it is treated as untrusted data.")
    return ParentScanResult(
        injection_detected=injection,
        sensitive_data_detected=bool(leak_reason),
        reason=" ".join(reasons),
        excerpt=redact_sensitive(text)[:280],
    )
