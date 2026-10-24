"""SQLAlchemy models and small CRUD helpers for synthetic training data."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all tables."""


class Parent(Base):
    __tablename__ = "parent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="hi-IN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionRecord(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"), index=True, nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    debrief_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class TurnRecord(Base):
    __tablename__ = "turn"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("session.id"), index=True, nullable=False)
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tactic_tag: Mapped[str | None] = mapped_column(String(30), nullable=True)
    response_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileRecord(Base):
    __tablename__ = "profile"

    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"), primary_key=True)
    per_tactic_resilience: Mapped[str] = mapped_column(Text, default="{}")
    sessions_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyContactRecord(Base):
    __tablename__ = "family_contact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"), index=True, nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), default="sms")


def create_parent(db: Session, name: str, language: str = "hi-IN") -> Parent:
    parent = Parent(name=name.strip() or "Demo Parent", language=language)
    db.add(parent)
    db.flush()
    return parent


def find_parent_by_name(db: Session, name: str) -> Parent | None:
    normalized = name.strip().lower()
    if not normalized:
        return None
    return db.scalar(select(Parent).where(func.lower(Parent.name) == normalized).limit(1))


def get_parent(db: Session, parent_id: int) -> Parent | None:
    return db.get(Parent, parent_id)


def create_session_record(
    db: Session,
    *,
    session_id: str,
    parent_id: int,
    scenario: str,
    difficulty: str,
) -> SessionRecord:
    record = SessionRecord(
        id=session_id,
        parent_id=parent_id,
        scenario=scenario,
        difficulty=difficulty,
        started_at=utcnow(),
    )
    db.add(record)
    db.flush()
    return record


def get_session_record(db: Session, session_id: str) -> SessionRecord | None:
    return db.get(SessionRecord, session_id)


def add_turn_record(
    db: Session,
    *,
    session_id: str,
    speaker: str,
    text: str,
    tactic_tag: str | None = None,
    response_type: str | None = None,
    risk_score: int | None = None,
) -> TurnRecord:
    record = TurnRecord(
        session_id=session_id,
        speaker=speaker,
        text=text,
        tactic_tag=tactic_tag,
        response_type=response_type,
        risk_score=risk_score,
        created_at=utcnow(),
    )
    db.add(record)
    db.flush()
    return record


def finish_session_record(
    db: Session,
    session_id: str,
    *,
    score: int,
    debrief_json: str,
) -> None:
    record = db.get(SessionRecord, session_id)
    if record is None:
        return
    record.ended_at = utcnow()
    record.score = score
    record.debrief_json = debrief_json


def get_turns_for_session(db: Session, session_id: str) -> list[TurnRecord]:
    return list(
        db.scalars(
            select(TurnRecord).where(TurnRecord.session_id == session_id).order_by(TurnRecord.id)
        )
    )


def get_or_create_profile_row(db: Session, parent_id: int) -> ProfileRecord:
    row = db.get(ProfileRecord, parent_id)
    if row is None:
        row = ProfileRecord(parent_id=parent_id, per_tactic_resilience="{}", sessions_count=0)
        db.add(row)
        db.flush()
    return row


def get_family_contacts(db: Session, parent_id: int) -> list[FamilyContactRecord]:
    return list(
        db.scalars(
            select(FamilyContactRecord)
            .where(FamilyContactRecord.parent_id == parent_id)
            .order_by(FamilyContactRecord.id)
        )
    )


def add_family_contact(
    db: Session,
    *,
    parent_id: int,
    contact_name: str,
    channel: str = "sms",
) -> FamilyContactRecord:
    contact = FamilyContactRecord(
        parent_id=parent_id,
        contact_name=contact_name,
        channel=channel,
    )
    db.add(contact)
    db.flush()
    return contact
