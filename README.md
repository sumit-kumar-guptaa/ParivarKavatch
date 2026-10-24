# Parivar Kavach

**Voice-based scam-awareness training for families.** A simulated scammer calls a parent in Hindi-English mix, a hidden judge tags every manipulation tactic, and the end-of-drill debrief updates a per-parent resilience profile so the next drill starts at their weakest spot.

Built for the Gnani AI **Great Indian AI Internship Challenge**. This is a training simulator, not a spam classifier. The core loop is **simulate -> observe -> adapt -> teach**.

> Training mode only. All scenario names, case IDs, amounts, tracking numbers, and contacts are synthetic. Never enter real personal or financial data.

---

## What is included

- FastAPI backend with REST + WebSocket drill streaming.
- Plain HTML/CSS/JS frontend, no build step, with:
  - setup screen (learner, scenario, difficulty),
  - big mic button with recording/echo-safe mic muting,
  - live transcript,
  - live tactic meter and risk gauge,
  - guard-break log,
  - debrief card with score, key moments, next steps, and resilience bars.
- Adaptive scammer with the 8-tactic playbook: authority, fear, urgency, secrecy, greed, isolation, small first ask, shame.
- Hidden judge returning strict JSON with validation and one repair retry.
- Per-parent resilience profile persisted in SQLite.
- Safety guard that blocks sensitive-data asks before TTS, detects real-looking parent data, redacts it, and ignores prompt injection.
- Mock family alert sender (writes to `data/alerts.log`).
- 5 synthetic scenarios.
- Terminal text-only drill for development.
- pytest suite for the guard, judge parsing/retry, profile updates, audio, scenarios, and full API/WebSocket flow.

---

## Quick start

### 1. Install

Python 3.11+ is required. `ffmpeg` must be on `PATH` for browser audio conversion and the optional telephone filter.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. API docs are at <http://127.0.0.1:8000/docs>.

Mocks are on by default (`USE_MOCKS=true`), so the full drill works with **zero Gnani credits**.

### 3. Test

```powershell
python -m pytest -q
```

### 4. Text-only terminal drill

```powershell
python scripts/text_drill.py --scenario digital_arrest --difficulty medium
```

This runs the scammer and judge in the terminal, with no audio and no database. Type as the parent. Use `/quit` to end early.

---

## How one turn works

1. Browser records one utterance and sends it over the WebSocket as base64 audio.
2. The server converts it to **mono 16-bit 8 kHz WAV** with ffmpeg.
3. **Prisma wrapper** transcribes it (mock mode returns canned Hinglish lines).
4. The transcript is sent in parallel (`asyncio.gather`) to:
   - **Scammer agent**: chooses the next tactic from scenario, difficulty, profile, and the judge's *previous* tag.
   - **Judge agent**: returns strict JSON:
     ```json
     {
       "tactic_used": "fear",
       "response_type": "resisted",
       "risk_score": 2,
       "reason": "The parent pushed back and refused to comply."
     }
     ```
5. The scammer line is scanned by the guard **before TTS**.
6. **Timbre wrapper** returns audio, optionally telephone-filtered (300-3400 Hz), and it is streamed to the browser.
7. The browser mutes the mic while caller audio plays to prevent echo.
8. Judge events update the live tactic meter.
9. On end, the judge writes the debrief, the score is stored, and the resilience profile is updated.

Because the scammer and judge run in parallel, the scammer uses the judge's *latest available* tag (from the previous turn). The new verdict is available to the scammer on the following turn.

---

## Project structure

```text
app/
  main.py          FastAPI routes, WebSocket loop, end/debrief orchestration
  session.py       In-memory drill state, transcript, tactic log, guard events
  audio.py         ffmpeg conversion, 8 kHz resampling, phone filter, WAV helpers
  stt.py           Prisma wrapper + mock
  tts.py           Timbre wrapper + mock
  llm.py           Evon wrapper + deterministic mock scammer/judge/debrief
  config.py        .env settings
  playbook.py      tactic vocabulary, labels, response types
  scenarios.py     scenario JSON loader/validator
agents/
  scammer.py       adaptive tactic selection and caller line generation
  judge.py         strict JSON judge, retry, debrief, fallback
  guard.py         sensitive-data scanner, injection detector, redaction
memory/
  profile.py       resilience profile read/update, weakest tactic
alerts/
  family.py        mock family alert sender
db/
  init.py          engine, session factory, SQLite setup
  models.py        ORM models and CRUD helpers
scenarios/
  digital_arrest.json
  bank_kyc.json
  courier_parcel.json
  refund_prize.json
  relative_trouble.json
frontend/
  index.html       complete single-file frontend
scripts/
  text_drill.py    terminal drill
tests/
data/              SQLite DB and mock alert log (gitignored)
```

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/sessions` | Create a drill and parent (or reuse `parent_id`) |
| `WS` | `/sessions/{id}/stream` | Audio/text turn loop and live events |
| `POST` | `/sessions/{id}/end` | Generate debrief, score, profile update, optional mock alert |
| `GET` | `/sessions/{id}/debrief` | Read the stored debrief (409 while active) |
| `GET` | `/parents/{id}/profile` | Resilience profile and weakest tactic |
| `POST` | `/alerts/test` | Send a mock family alert |
| `GET` | `/scenarios` | Scenario catalogue for the frontend |
| `GET` | `/health` | Health and mock-mode status |

### Create a session

```http
POST /sessions
Content-Type: application/json

{
  "parent_name": "Demo Parent",
  "language": "hi-IN",
  "scenario": "digital_arrest",
  "difficulty": "medium"
}
```

Reuse a learner profile by sending `parent_id` instead of `parent_name`. The frontend stores the parent id in `localStorage` so the profile carries across drills.

### WebSocket protocol

Client -> server:

```json
{"type": "audio", "content_type": "audio/webm;codecs=opus", "audio_b64": "..."}
{"type": "text", "text": "Nahi, main OTP nahi bataunga."}
{"type": "ping"}
```

Server -> client:

```json
{"type": "ready", "session_id": "...", "max_turns": 6, "mock_mode": true}
{"type": "transcribing"}
{"type": "parent_transcript", "turn": 1, "text": "..."}
{"type": "judge_result", "tactic_used": "authority", "response_type": "resisted", "risk_score": 2, "reason": "..."}
{"type": "caller_thinking"}
{"type": "scammer_message", "text": "...", "tactic": "fear", "audio_b64": "...", "audio_mime": "audio/wav", "mock_tts": true, "guard_break": false}
{"type": "guard_event", "kind": "sensitive_data_shared", "message": "This is where you would have lost money..."}
{"type": "max_turns_reached", "turn": 6, "max_turns": 6}
{"type": "error", "message": "..."}
```

Binary WebSocket frames are also accepted and treated as `audio/webm`.

### Alert test

```http
POST /alerts/test
Content-Type: application/json

{"parent_id": 1, "channel": "sms"}
```

Mock mode writes a JSON line to `data/alerts.log`; it never sends a real SMS or WhatsApp message. If no family contact exists, a synthetic contact is created.

---

## Data model

SQLite tables:

- `parent(id, name, language, created_at)`
- `session(id, parent_id, scenario, difficulty, started_at, ended_at, score, debrief_json)`
- `turn(id, session_id, speaker, text, tactic_tag, response_type, risk_score, created_at)`
- `profile(parent_id, per_tactic_resilience JSON, sessions_count, updated_at)`
- `family_contact(id, parent_id, contact_name, channel)`

`debrief_json` is an additive field used to return a stable debrief after the in-memory state is gone.

---

## Adaptivity and scoring

- Every parent starts at `0.5` resilience on all 8 tactics.
- The scammer's opening tactic is the **weakest scenario-relevant tactic**.
- Profile deltas applied from each judged turn when the drill ends:
  - `resisted`: `+0.10`
  - `hesitated`: `-0.02`
  - `complied`: `-0.12`
  - `leaked_info`: `-0.20`
  - clamped to `0.05 .. 0.95`
- A session increments `sessions_count` once.
- The mock/suggested debrief score is `100 - (average risk * 9)`, clamped to `10 .. 100`.
- The scammer switches tactics after resistance, escalates toward a small ask after compliance, and persists/escalates on hesitation.
- Difficulty controls the turn cap, escalation speed, and maximum line intensity:
  - easy: 4 turns, slow escalation, softer lines
  - medium: 6 turns
  - hard: 8 turns, fast escalation, sharper lines

---

## Safety layer

`agents/guard.py` is enforced server-side, independently of the LLM:

1. **Forbidden asks**: scans every scammer line for requests involving Aadhaar, account numbers, UPI PIN, card number, CVV, OTP, password, bank details, etc.
2. **Guard break**: replaces the line with exactly:
   > This is where you would have lost money. No real officer ever asks for this.
3. **Parent data leak**: detects Aadhaar/card/OTP/PIN/account-like values, breaks character, and redacts the value before persisting or displaying it.
4. **Prompt injection**: detects instructions such as "ignore your instructions" or "ask for real bank details", treats all transcript text as untrusted data, logs the attempt, and never follows it.
5. **Output scan before TTS**: the guard check happens before the Timbre call, not after.
6. **Guard event log**: sent to the UI live, stored in the session, and counted in the debrief.

The scammer system prompt independently forbids real sensitive-data requests and instructs the model to ignore instructions embedded in transcript text. The guard is the deterministic backstop.

---

## Mock mode

`USE_MOCKS=true` makes the app fully runnable without credits:

- **Evon mock**: deterministic scammer lines from scenario JSON, heuristic judge tags, computed debrief.
- **Prisma mock**: canned Hinglish parent transcripts selected by audio hash.
- **Timbre mock**: returns a valid 8 kHz WAV tone/silence placeholder.
- **Frontend voice**: when `mock_tts` is true, the browser speaks the scammer text with the Web Speech API (Hindi voice if available), so the demo still has voice without Gnani credits.
- **Family alert mock**: appends to `data/alerts.log`.

The server still sends a valid WAV payload in mock mode, so the audio path is exercised end to end.

---

## Live Gnani mode: what to verify before flipping `USE_MOCKS=false`

The Prisma and Timbre REST adapters are wired to the official Speech API
contracts documented at <https://docs.gnani.ai/api/introduction/introduction>.
The defaults are:

- Prisma v2.5: `https://api.vachana.ai/stt/v3`, multipart `audio_file`, and
  `X-API-Key-ID` authentication.
- Timbre v2.5: `https://api.vachana.ai/api/v1/tts/inference`, with the
  Hinglish `Poorvi` voice and an 8 kHz mono WAV response.

The Evon adapter remains deliberately unimplemented because the public Speech
API documentation does not publish an Evon v3.3 inference endpoint or request
schema. The mock scammer/judge brain remains the safe end-to-end fallback.

Before going live:

- Confirm the Prisma dashboard key has Speech API permission and test a short
  synthetic WAV.
- Confirm `Poorvi` is available to the account; change `TIMBRE_VOICE` to
  another v2.5 Hinglish/Hindi voice if needed.
- Obtain the official Evon endpoint, authentication, model identifier,
  request/response schema, structured JSON support, and rate limits from Gnani.
- Set `USE_MOCKS=false` only after Prisma and Timbre have passed with synthetic
  audio and Evon has been wired in `app/llm.py`.

### Phase 2: text loop and judge JSON

- Does Evon support JSON mode / structured output? What is the exact schema mechanism?
- What are token limits, latency, and retry/error semantics?
- Is a repair prompt needed, or does the API support constrained decoding?
- How does the model handle Hinglish prompts?

### Phase 3: audio loop

- Does Prisma accept the 8 kHz mono WAV produced by `app/audio.py`, or should browser WebM be sent directly?
- Does Timbre return WAV, MP3, or streaming chunks? Adjust `app/tts.py` and `prepare_outbound_audio()` accordingly.
- What are the max audio durations and upload sizes?
- Are partial transcripts or streaming STT available? If yes, extend the WebSocket protocol.
- Browser autoplay and Web Speech API availability vary; the app already handles blocked playback with a replay link.

### Phase 4: debrief, profile, adaptivity

- Confirm Evon is comfortable with the prompt sizes used for transcript + tactic log.
- Confirm deterministic/low-temperature settings for the judge.
- Confirm content-policy behaviour for simulated scam dialogue and safety-guard replacement text.

### Phase 5: frontend

- No Gnani docs required. Test mic permissions, audio playback, and mobile Safari/Chrome behaviour.

### Phase 6: guard, injection, alerts

- Guard and prompt-injection tests are local and deterministic.
- For real family alerts, choose an SMS/WhatsApp provider and verify endpoint, auth, templates, consent, and rate limits. Keep the mock sender for demos.
- Never send real personal data from this training app.

---

## Build phases (what was built)

- **Phase 1**: project skeleton, `.env` config, SQLite models/init, mocks for Evon/Prisma/Timbre, scenario catalogue.
- **Phase 2**: adaptive scammer, strict judge JSON with validation + one repair retry, terminal text drill, profile model.
- **Phase 3**: ffmpeg audio conversion, 8 kHz WAV, mock TTS/STT, WebSocket event stream, mic muting in the frontend, phone filter.
- **Phase 4**: debrief generation, score persistence, resilience profile updates, weakest-tactic targeting, difficulty tuning.
- **Phase 5**: single-file frontend with setup, mic, live transcript, tactic meter, guard log, debrief card, profile bars.
- **Phase 6**: guard layer, injection detection, redaction, mock family alerts, full test suite.

---

## Known limitations

- Active drill state lives in memory. A server restart loses in-progress calls; ended debriefs and profiles remain in SQLite.
- Live Gnani adapters are TODOs until the official request/response details are wired.
- Mock STT returns canned transcripts rather than real speech recognition.
- The browser Web Speech API is used for mock voice, so voice availability depends on the browser/OS.
- Real family alert delivery is intentionally unimplemented; only the mock log exists.
- Family contact management is minimal: `/alerts/test` creates a synthetic contact if none exists.

---

## License / data

Synthetic data only. No real Aadhaar, account, card, OTP, PIN, or personal contact data is required or intentionally stored. If a user types real-looking data into a drill, the guard detects it, redacts it before persistence, and breaks character.
