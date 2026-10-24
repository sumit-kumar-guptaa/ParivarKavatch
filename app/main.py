"""FastAPI app: session lifecycle, WebSocket drill loop, debrief, and profiles."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from agents.guard import GUARD_MESSAGE, redact_sensitive, scan_parent_text, scan_scammer_line
from agents.judge import JudgeAgent, JudgeParseError, JudgeVerdict, fallback_debrief
from agents.scammer import ScammerAgent
from alerts.family import send_family_alert
from app import llm, stt, tts
from app.audio import AudioProcessingError, normalize_for_stt, prepare_outbound_audio
from app.config import settings
from app.playbook import Difficulty
from app.scenarios import ScenarioNotFound, load_scenario, scenario_summaries
from app.session import DrillSession, create_drill_session, get_session
from db.init import db_session, init_db
from db.models import (
    add_family_contact,
    add_turn_record,
    create_parent,
    create_session_record,
    find_parent_by_name,
    finish_session_record,
    get_family_contacts,
    get_parent,
    get_session_record,
)
from memory.profile import get_profile_snapshot, update_profile_from_turns

logger = logging.getLogger("parivar_kavach")
logging.basicConfig(level=logging.INFO)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
scammer_agent = ScammerAgent()
judge_agent = JudgeAgent()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Voice-based scam-awareness training simulator. Synthetic data only.",
    lifespan=lifespan,
)


class SessionCreate(BaseModel):
    parent_id: int | None = None
    parent_name: str = Field(default="Demo Parent", min_length=1, max_length=120)
    language: str = "hi-IN"
    scenario: str = "digital_arrest"
    difficulty: Difficulty = "medium"


class AlertTestRequest(BaseModel):
    parent_id: int
    contact_name: str | None = Field(default=None, max_length=120)
    channel: Literal["sms", "whatsapp", "call"] = "sms"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "use_mocks": settings.use_mocks,
        "use_mock_stt": settings.use_mock_stt,
        "use_mock_tts": settings.use_mock_tts,
        "ffmpeg_phone_filter": settings.phone_filter,
    }


@app.get("/scenarios")
async def list_scenarios() -> list[dict[str, Any]]:
    return scenario_summaries()


@app.post("/sessions", status_code=201)
async def create_session(payload: SessionCreate) -> dict[str, Any]:
    try:
        load_scenario(payload.scenario)
    except ScenarioNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_session() as db:
        if payload.parent_id is not None:
            parent = get_parent(db, payload.parent_id)
            if parent is None:
                raise HTTPException(status_code=404, detail="Parent not found")
        else:
            parent = find_parent_by_name(db, payload.parent_name)
            if parent is None:
                parent = create_parent(db, payload.parent_name, payload.language)
        parent_id = parent.id
        parent_name = parent.name

    state = create_drill_session(
        parent_id=parent_id,
        language=payload.language,
        scenario_id=payload.scenario,
        difficulty=payload.difficulty,
    )
    with db_session() as db:
        create_session_record(
            db,
            session_id=state.id,
            parent_id=parent_id,
            scenario=payload.scenario,
            difficulty=payload.difficulty,
        )

    return {
        "session_id": state.id,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "scenario": payload.scenario,
        "scenario_title": state.scenario.get("title"),
        "difficulty": payload.difficulty,
        "max_turns": state.max_turns,
    }


@app.get("/sessions/{session_id}/debrief")
async def get_debrief(session_id: str) -> dict[str, Any]:
    state = get_session(session_id)
    if state is not None:
        if state.status != "ended" or state.debrief is None:
            raise HTTPException(status_code=409, detail="Session is still active")
        return {
            "session_id": state.id,
            "score": state.score,
            "debrief": state.debrief,
            "profile": get_profile_snapshot(state.parent_id),
            "alerts": [],
        }

    with db_session() as db:
        record = get_session_record(db, session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if record.ended_at is None or not record.debrief_json:
            raise HTTPException(status_code=409, detail="Session is still active")
        score = record.score
        debrief = json.loads(record.debrief_json)
        parent_id = record.parent_id
    return {
        "session_id": session_id,
        "score": score,
        "debrief": debrief,
        "profile": get_profile_snapshot(parent_id),
        "alerts": [],
    }


@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str) -> dict[str, Any]:
    state = get_session(session_id)
    if state is None:
        return await _ended_response_from_db(session_id)

    async with state.lock:
        if state.status == "ended" and state.debrief is not None:
            return await _ended_response(state)

        judge_error: str | None = None
        try:
            debrief_model = await judge_agent.make_debrief(state)
        except (JudgeParseError, llm.ProviderNotConfigured, llm.ProviderError) as exc:
            judge_error = str(exc)
            logger.warning("Using fallback debrief: %s", exc)
            debrief_model = fallback_debrief(state)

        debrief_payload = debrief_model.model_dump(mode="json")
        if judge_error:
            debrief_payload["judge_fallback"] = True

        with db_session() as db:
            finish_session_record(
                db,
                session_id,
                score=debrief_model.score,
                debrief_json=json.dumps(debrief_payload, ensure_ascii=False),
            )

        profile = update_profile_from_turns(state.parent_id, state.turns)
        alerts: list[dict[str, Any]] = []
        if settings.family_alert_on_end and debrief_model.score <= settings.family_alert_score_threshold:
            alerts = await _send_end_alerts(
                parent_id=state.parent_id,
                session_id=state.id,
                score=debrief_model.score,
                weakest_label=profile.get("weakest_label", "awareness"),
            )

        state.status = "ended"
        state.score = debrief_model.score
        state.debrief = debrief_payload
        return {
            "session_id": state.id,
            "score": debrief_model.score,
            "debrief": debrief_payload,
            "profile": profile,
            "alerts": alerts,
        }


@app.get("/parents/{parent_id}/profile")
async def get_parent_profile(parent_id: int) -> dict[str, Any]:
    with db_session() as db:
        if get_parent(db, parent_id) is None:
            raise HTTPException(status_code=404, detail="Parent not found")
    return get_profile_snapshot(parent_id)


@app.post("/alerts/test")
async def test_family_alert(payload: AlertTestRequest) -> dict[str, Any]:
    with db_session() as db:
        parent = get_parent(db, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent not found")
        contacts = get_family_contacts(db, payload.parent_id)
        if payload.contact_name:
            contact_name = payload.contact_name
            channel = payload.channel
        elif contacts:
            contact_name = contacts[0].contact_name
            channel = contacts[0].channel
        else:
            contact_name = "Demo Family Member"
            channel = payload.channel
            add_family_contact(
                db,
                parent_id=payload.parent_id,
                contact_name=contact_name,
                channel=channel,
            )
        parent_name = parent.name

    message = (
        f"Parivar Kavach test alert for {parent_name}. This is a mock delivery; "
        "no real personal data is included."
    )
    try:
        result = await send_family_alert(
            parent_id=payload.parent_id,
            contact_name=contact_name,
            channel=channel,
            message=message,
        )
    except llm.ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"parent_name": parent_name, **result}


@app.websocket("/sessions/{session_id}/stream")
async def session_stream(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    state = get_session(session_id)
    if state is None:
        await websocket.send_json({"type": "error", "message": "Session not found. Create a new drill."})
        await websocket.close(code=4404)
        return
    if state.status == "ended":
        await websocket.send_json({"type": "error", "message": "This drill has already ended."})
        await websocket.close(code=4409)
        return

    await websocket.send_json(
        {
            "type": "ready",
            "session_id": state.id,
            "parent_id": state.parent_id,
            "language": state.language,
            "scenario": state.scenario_id,
            "scenario_title": state.scenario.get("title"),
            "difficulty": state.difficulty,
            "max_turns": state.max_turns,
            "mock_mode": settings.use_mocks,
            "use_mock_stt": settings.use_mock_stt,
        }
    )
    try:
        await _send_opening(state, websocket)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await _handle_user_turn(
                    state,
                    websocket,
                    audio=message["bytes"],
                    content_type="audio/webm",
                )
                continue
            raw_text = message.get("text")
            if raw_text is None:
                continue
            try:
                event = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid control message."})
                continue
            if not isinstance(event, dict):
                await websocket.send_json({"type": "error", "message": "Invalid control message."})
                continue

            event_type = event.get("type")
            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif event_type == "text":
                await _handle_user_turn(state, websocket, text=str(event.get("text", "")))
            elif event_type == "audio":
                try:
                    audio = base64.b64decode(str(event.get("audio_b64", "")), validate=True)
                except (ValueError, TypeError):
                    await websocket.send_json({"type": "error", "message": "Invalid audio encoding."})
                    continue
                await _handle_user_turn(
                    state,
                    websocket,
                    audio=audio,
                    content_type=str(event.get("content_type", "audio/webm")),
                )
            else:
                await websocket.send_json({"type": "error", "message": "Unknown event type."})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception:  # pragma: no cover - defensive boundary
        logger.exception("WebSocket failure for session %s", session_id)
        try:
            await websocket.send_json(
                {"type": "error", "message": "The call hit an internal error. Please retry."}
            )
        except Exception:
            pass


async def _send_opening(state: DrillSession, websocket: WebSocket) -> None:
    async with state.lock:
        if state.intro_sent:
            return
        if state.status != "active":
            return
        profile = get_profile_snapshot(state.parent_id)["per_tactic_resilience"]
        line = await scammer_agent.opening(state, profile)
        outbound = scan_scammer_line(line.text)
        guard_break = outbound.activated
        final_text = outbound.text

        state.current_tactic = line.tactic
        if guard_break:
            state.add_guard_event(
                kind=outbound.kind,
                reason=outbound.reason,
                excerpt=redact_sensitive(line.text),
            )
            state.add_turn("guard", final_text)
            _persist_turn(
                state,
                speaker="guard",
                text=final_text,
                tactic_tag=line.tactic,
            )
        else:
            state.add_turn("scammer", final_text, tactic_tag=line.tactic)
            _persist_turn(
                state,
                speaker="scammer",
                text=final_text,
                tactic_tag=line.tactic,
            )

        audio_b64 = await _render_voice(final_text)
        state.intro_sent = True
        await websocket.send_json(
            {
                "type": "scammer_message",
                "turn": 0,
                "text": final_text,
                "tactic": line.tactic,
                "intensity": line.intensity,
                "guard_break": guard_break,
                "audio_b64": audio_b64,
                "audio_mime": "audio/wav",
                "mock_tts": settings.use_mock_tts,
            }
        )
        if guard_break:
            await websocket.send_json(
                {
                    "type": "guard_event",
                    "turn": 0,
                    "kind": outbound.kind,
                    "message": GUARD_MESSAGE,
                    "reason": outbound.reason,
                }
            )


async def _handle_user_turn(
    state: DrillSession,
    websocket: WebSocket,
    *,
    text: str | None = None,
    audio: bytes | None = None,
    content_type: str | None = None,
) -> None:
    async with state.lock:
        if state.status != "active":
            await websocket.send_json({"type": "error", "message": "This drill has ended."})
            return
        if state.turn_count >= state.max_turns:
            await websocket.send_json(
                {
                    "type": "max_turns_reached",
                    "turn": state.turn_count,
                    "max_turns": state.max_turns,
                    "message": "Turn limit reached. End the drill to see your debrief.",
                }
            )
            return

        if audio is not None:
            await websocket.send_json({"type": "transcribing"})
            try:
                wav = await normalize_for_stt(audio, content_type)
                parent_text = await stt.transcribe(
                    wav,
                    language=state.language,
                    content_type="audio/wav",
                )
            except (AudioProcessingError, llm.ProviderNotConfigured, llm.ProviderError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                return
        else:
            parent_text = (text or "").strip()
        if not parent_text:
            await websocket.send_json({"type": "error", "message": "No speech was detected. Please try again."})
            return

        state.turn_count += 1
        parent_scan = scan_parent_text(parent_text)
        if parent_scan.injection_detected:
            state.injection_attempts += 1
            state.add_guard_event(
                kind="prompt_injection",
                reason="Instruction-like parent text was treated as untrusted and ignored.",
                excerpt=parent_scan.excerpt,
            )
            await websocket.send_json(
                {
                    "type": "guard_event",
                    "turn": state.turn_count,
                    "kind": "prompt_injection",
                    "message": "Instruction-like text was ignored. The drill stays in role.",
                    "reason": parent_scan.reason,
                }
            )
        if parent_scan.sensitive_data_detected:
            state.add_guard_event(
                kind="sensitive_data_shared",
                reason=parent_scan.reason,
                excerpt=parent_scan.excerpt,
            )

        stored_parent_text = (
            redact_sensitive(parent_text) if parent_scan.sensitive_data_detected else parent_text
        )
        await websocket.send_json(
            {
                "type": "parent_transcript",
                "turn": state.turn_count,
                "text": stored_parent_text,
                "guard_notice": parent_scan.reason if parent_scan.activated else "",
            }
        )

        profile = get_profile_snapshot(state.parent_id)["per_tactic_resilience"]
        judge_task = judge_agent.evaluate(state, parent_text, state.current_tactic)
        scammer_task = scammer_agent.respond(
            state,
            profile,
            parent_text,
            state.last_verdict,
        )
        judge_result, scammer_result = await asyncio.gather(
            judge_task, scammer_task, return_exceptions=True
        )
        if isinstance(scammer_result, Exception):
            logger.warning("Scammer generation failed: %s", scammer_result)
            state.turn_count -= 1
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "The caller line could not be generated. Please try again.",
                }
            )
            return
        line = scammer_result
        if isinstance(judge_result, Exception):
            logger.warning("Judge failed after retry, applying fallback: %s", judge_result)
            verdict = JudgeVerdict(
                tactic_used=state.current_tactic or "authority",
                response_type="leaked_info" if parent_scan.sensitive_data_detected else "hesitated",
                risk_score=10 if parent_scan.sensitive_data_detected else 5,
                reason="Judge output could not be validated after retry; conservative fallback applied.",
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
        state.add_turn(
            "parent",
            stored_parent_text,
            tactic_tag=verdict.tactic_used,
            response_type=verdict.response_type,
            risk_score=verdict.risk_score,
        )
        _persist_turn(
            state,
            speaker="parent",
            text=stored_parent_text,
            tactic_tag=verdict.tactic_used,
            response_type=verdict.response_type,
            risk_score=verdict.risk_score,
        )
        await websocket.send_json(
            {
                "type": "judge_result",
                "turn": state.turn_count,
                "tactic_used": verdict.tactic_used,
                "response_type": verdict.response_type,
                "risk_score": verdict.risk_score,
                "reason": safe_reason,
            }
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
        if guard_break:
            await websocket.send_json(
                {
                    "type": "guard_event",
                    "turn": state.turn_count,
                    "kind": "sensitive_data_shared" if parent_scan.sensitive_data_detected else outbound.kind,
                    "message": GUARD_MESSAGE,
                    "reason": (
                        parent_scan.reason
                        if parent_scan.sensitive_data_detected
                        else outbound.reason
                    ),
                }
            )

        state.current_tactic = line.tactic
        if guard_break:
            state.add_turn("guard", final_text, tactic_tag=line.tactic)
            _persist_turn(state, speaker="guard", text=final_text, tactic_tag=line.tactic)
        else:
            state.add_turn("scammer", final_text, tactic_tag=line.tactic)
            _persist_turn(state, speaker="scammer", text=final_text, tactic_tag=line.tactic)

        await websocket.send_json({"type": "caller_thinking"})
        audio_b64 = await _render_voice(final_text)
        await websocket.send_json(
            {
                "type": "scammer_message",
                "turn": state.turn_count,
                "text": final_text,
                "tactic": line.tactic,
                "intensity": line.intensity,
                "guard_break": guard_break,
                "audio_b64": audio_b64,
                "audio_mime": "audio/wav",
                "mock_tts": settings.use_mock_tts,
            }
        )
        if state.turn_count >= state.max_turns:
            await websocket.send_json(
                {
                    "type": "max_turns_reached",
                    "turn": state.turn_count,
                    "max_turns": state.max_turns,
                    "message": "Turn limit reached. End the drill to see your debrief.",
                }
            )


async def _render_voice(text: str) -> str | None:
    try:
        audio_bytes, mime_type = await tts.synthesize(text)
        prepared = await prepare_outbound_audio(audio_bytes, mime_type)
        return base64.b64encode(prepared).decode("ascii")
    except Exception as exc:  # voice failure must never end the drill
        logger.warning("TTS unavailable, sending text only: %s", exc)
        return None


def _persist_turn(
    state: DrillSession,
    *,
    speaker: str,
    text: str,
    tactic_tag: str | None = None,
    response_type: str | None = None,
    risk_score: int | None = None,
) -> None:
    try:
        with db_session() as db:
            add_turn_record(
                db,
                session_id=state.id,
                speaker=speaker,
                text=text,
                tactic_tag=tactic_tag,
                response_type=response_type,
                risk_score=risk_score,
            )
    except Exception:  # pragma: no cover - persistence must not kill the call
        logger.exception("Could not persist turn for session %s", state.id)


async def _send_end_alerts(
    *,
    parent_id: int,
    session_id: str,
    score: int,
    weakest_label: str,
) -> list[dict[str, Any]]:
    with db_session() as db:
        contacts = get_family_contacts(db, parent_id)
        contact_data = [(contact.contact_name, contact.channel) for contact in contacts]
    if not contact_data:
        return []
    message = (
        "Parivar Kavach training alert: the learner completed a scam-awareness drill "
        f"with a score of {score}/100. Next focus: {weakest_label}. "
        "This is a synthetic training alert; no real data is included."
    )
    results: list[dict[str, Any]] = []
    for contact_name, channel in contact_data:
        try:
            results.append(
                await send_family_alert(
                    parent_id=parent_id,
                    contact_name=contact_name,
                    channel=channel,
                    message=message,
                    session_id=session_id,
                )
            )
        except Exception as exc:  # alert delivery must never block the debrief
            logger.warning("Family alert failed for contact %s: %s", contact_name, exc)
            results.append(
                {
                    "sent": False,
                    "contact_name": contact_name,
                    "error": "Family alert delivery failed.",
                }
            )
    return results


async def _ended_response(state: DrillSession) -> dict[str, Any]:
    return {
        "session_id": state.id,
        "score": state.score,
        "debrief": state.debrief,
        "profile": get_profile_snapshot(state.parent_id),
        "alerts": [],
    }


async def _ended_response_from_db(session_id: str) -> dict[str, Any]:
    with db_session() as db:
        record = get_session_record(db, session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if record.ended_at is None or not record.debrief_json:
            raise HTTPException(status_code=409, detail="Session is still active")
        parent_id = record.parent_id
        score = record.score
        debrief = json.loads(record.debrief_json)
    return {
        "session_id": session_id,
        "score": score,
        "debrief": debrief,
        "profile": get_profile_snapshot(parent_id),
        "alerts": [],
    }
