"""Shared manipulation-tactic vocabulary and training guidance."""

from typing import Literal

TACTICS: tuple[str, ...] = (
    "authority",
    "fear",
    "urgency",
    "secrecy",
    "greed",
    "isolation",
    "small_ask",
    "shame",
)

TACTIC_LABELS: dict[str, str] = {
    "authority": "Authority",
    "fear": "Fear",
    "urgency": "Urgency",
    "secrecy": "Secrecy",
    "greed": "Greed",
    "isolation": "Isolation",
    "small_ask": "Small first ask",
    "shame": "Shame",
}

TACTIC_TIPS: dict[str, str] = {
    "authority": "Verify the caller independently. Real agencies do not run arrests over a phone call.",
    "fear": "Slow down. Fear is the tool, not proof. Hang up and call a family member.",
    "urgency": "A deadline invented on the phone is a red flag. Take all the time you need.",
    "secrecy": "Secrecy protects the scammer. Tell someone you trust what is happening.",
    "greed": "Unexpected refunds or prizes are bait. Never act on unsolicited winnings.",
    "isolation": "Staying on the line alone is dangerous. Involve a family member immediately.",
    "small_ask": "A small request is often the first step. Do not read IDs, codes, or numbers to a caller.",
    "shame": "Not knowing a process is not a crime. Shame is used to silence you.",
}

RESPONSE_TYPES: tuple[str, ...] = (
    "resisted",
    "hesitated",
    "complied",
    "leaked_info",
)

ResponseType = Literal["resisted", "hesitated", "complied", "leaked_info"]
Difficulty = Literal["easy", "medium", "hard"]
TacticName = Literal[
    "authority",
    "fear",
    "urgency",
    "secrecy",
    "greed",
    "isolation",
    "small_ask",
    "shame",
]
