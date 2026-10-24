"""In-memory drill state plus transcript, tactic, and guard event models."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.playbook import Difficulty
from app.scenarios import load_scenario

Speaker = Literal["scammer", "parent", "guard", "system"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TranscriptTurn(BaseModel):
    index: int
    speaker: Speaker
    text: str
    tactic_tag: str | None = None
    response_type: str | None = None
    risk_score: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class TacticEvent(BaseModel):
    turn: int
    tactic: str
    response_type: str
    risk_score: int
    reason: str = ""


class GuardEvent(BaseModel):
    turn: int
    kind: str
    reason: str
    excerpt: str = ""
    created_at: datetime = Field(default_factory=utcnow)


@dataclass
class DrillSession:
    id: str
    parent_id: int
    language: str
    scenario_id: str
    difficulty: Difficulty
    scenario: dict[str, Any]
    max_turns: int
    started_at: datetime = field(default_factory=utcnow)
    turns: list[TranscriptTurn] = field(default_factory=list)
    tactic_log: list[TacticEvent] = field(default_factory=list)
    guard_events: list[GuardEvent] = field(default_factory=list)
    turn_count: int = 0
    current_tactic: str | None = None
    last_verdict: dict[str, Any] | None = None
    status: Literal["active", "ended"] = "active"
    score: int | None = None
    debrief: dict[str, Any] | None = None
    intro_sent: bool = False
    injection_attempts: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def add_turn(
        self,
        speaker: Speaker,
        text: str,
        *,
        tactic_tag: str | None = None,
        response_type: str | None = None,
        risk_score: int | None = None,
    ) -> TranscriptTurn:
        turn = TranscriptTurn(
            index=len(self.turns),
            speaker=speaker,
            text=text,
            tactic_tag=tactic_tag,
            response_type=response_type,
            risk_score=risk_score,
        )
        self.turns.append(turn)
        return turn

    def add_tactic_event(
        self,
        *,
        turn: int,
        tactic: str,
        response_type: str,
        risk_score: int,
        reason: str = "",
    ) -> TacticEvent:
        event = TacticEvent(
            turn=turn,
            tactic=tactic,
            response_type=response_type,
            risk_score=risk_score,
            reason=reason,
        )
        self.tactic_log.append(event)
        return event

    def add_guard_event(self, *, kind: str, reason: str, excerpt: str = "") -> GuardEvent:
        event = GuardEvent(
            turn=self.turn_count,
            kind=kind,
            reason=reason,
            excerpt=excerpt[:280],
        )
        self.guard_events.append(event)
        return event

    def guard_activation_count(self) -> int:
        return sum(1 for event in self.guard_events if event.kind != "prompt_injection")

    def recent_history(self, limit: int = 6) -> list[dict[str, Any]]:
        return [turn.model_dump(mode="json") for turn in self.turns[-limit:]]


_SESSIONS: dict[str, DrillSession] = {}


def create_drill_session(
    *,
    parent_id: int,
    language: str = "hi-IN",
    scenario_id: str,
    difficulty: Difficulty,
) -> DrillSession:
    """Create and register a new in-memory session."""
    scenario = load_scenario(scenario_id)
    session = DrillSession(
        id=str(uuid.uuid4()),
        parent_id=parent_id,
        language=language,
        scenario_id=scenario_id,
        difficulty=difficulty,
        scenario=scenario,
        max_turns=settings.max_turns_for(difficulty),
    )
    _SESSIONS[session.id] = session
    return session


def register_session(session: DrillSession) -> DrillSession:
    _SESSIONS[session.id] = session
    return session


def get_session(session_id: str) -> DrillSession | None:
    return _SESSIONS.get(session_id)


def clear_sessions() -> None:
    """Test helper."""
    _SESSIONS.clear()
