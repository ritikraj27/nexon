# backend/main.py — FIXED VERSION
# ============================================================
# Fixes:
# 1. Passes original_text to command_processor so DB stores
#    clean text (not the [Visual context: ...] prefix)
# 2. Parallel execution only triggers for 2+ REAL action intents
#    (not for conversational messages)
# 3. Better error handling on all endpoints
# ============================================================

import os
import json
import asyncio
from typing import Optional, List
from datetime import datetime

from fastapi import (
    FastAPI, HTTPException, Depends, UploadFile,
    File, Form, WebSocket, WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlalchemy

from backend.config import APP_HOST, APP_PORT, CORS_ORIGINS, NEXON_HOME
from backend.db.models import Base
from backend.db.sessions import (
    init_db, get_db, SessionLocal,
    create_session, list_sessions, get_session,
    delete_session, switch_session,
    add_message, get_messages, get_context_messages,
    get_preference, set_preference,
    add_clipboard, get_clipboard_history
)
from backend.llm_engine import nexon_llm
from backend.command_processor import command_processor, clean_user_text_for_display, CONVERSATIONAL_INTENTS
from backend.speech.whisper_engine import whisper_engine, tts_engine

# ── Optional feature imports ─────────────────────────────────

try:
    from backend.memory.graph import MemoryGraph
    _MEMORY_OK = True
except Exception as e:
    print(f"[main] Memory: {e}")
    _MEMORY_OK = False
    MemoryGraph = None

try:
    from backend.predictive.intent_engine import PredictiveIntentEngine
    _PREDICT_OK = True
except Exception as e:
    print(f"[main] Predictive: {e}")
    _PREDICT_OK = False
    PredictiveIntentEngine = None

try:
    from backend.voice.stress_analyzer import voice_stress_analyzer
    _STRESS_OK = True
except Exception as e:
    print(f"[main] VoiceStress: {e}")
    _STRESS_OK = False
    voice_stress_analyzer = None

try:
    from backend.vision.screen_reader import screen_reader
    _SCREEN_OK = True
except Exception as e:
    print(f"[main] ScreenReader: {e}")
    _SCREEN_OK = False
    screen_reader = None

try:
    from backend.auth.biometric import biometric_auth
    _BIO_OK = True
except Exception as e:
    print(f"[main] Biometric: {e}")
    _BIO_OK = False
    biometric_auth = None

try:
    from backend.personality.style_engine import PersonalityStyleEngine
    _STYLE_OK = True
except Exception as e:
    print(f"[main] StyleEngine: {e}")
    _STYLE_OK = False
    PersonalityStyleEngine = None

try:
    from backend.agents.parallel_executor import ParallelExecutor, GestureMacroEngine
    _PARALLEL_OK = True
except Exception as e:
    print(f"[main] Parallel: {e}")
    _PARALLEL_OK = False
    ParallelExecutor   = None
    GestureMacroEngine = None

# ─────────────────────────────────────────────────────────────

app = FastAPI(title="NEXON AI OS Backend v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_db()
    db = SessionLocal()
    try:
        sessions = list_sessions(db)
        if not sessions:
            create_session(db, language="en")
        active = [k for k, v in {
            "memory":_MEMORY_OK,"predictive":_PREDICT_OK,"voice_stress":_STRESS_OK,
            "screen":_SCREEN_OK,"biometric":_BIO_OK,"personality":_STYLE_OK,"parallel":_PARALLEL_OK
        }.items() if v]
        print(f"[NEXON v2] Started. Sessions: {len(sessions)}. Features: {active}")
    finally:
        db.close()


# ── Pydantic Models ──────────────────────────────────────────

class ChatRequest(BaseModel):
    text        : str
    session_id  : int
    language    : str = "en"
    emotion     : str = "neutral"
    mode        : str = "text"
    user_id     : str = "default"
    gesture     : str = ""
    voice_stress: int = 0

class SessionCreate(BaseModel):
    language: str = "en"

class PreferenceSet(BaseModel):
    key  : str
    value: str

class TTSRequest(BaseModel):
    text    : str
    language: str = "en"

class MemoryStoreRequest(BaseModel):
    content    : str
    memory_type: str       = "fact"
    tags       : List[str] = []
    importance : float     = 0.5
    session_id : Optional[int] = None

class MemorySearchRequest(BaseModel):
    query      : str
    top_k      : int          = 5
    memory_type: Optional[str]= None

class ProfileCreate(BaseModel):
    name   : str
    avatar : str          = "👤"
    user_id: Optional[str]= None

class GestureMacroCreate(BaseModel):
    gesture_name: str
    macro_name  : str
    commands    : List[str]

class StyleFeedback(BaseModel):
    user_id : str = "default"
    feedback: str


# ── Health ───────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    llm_status = await nexon_llm.check_availability()
    return {
        "status"   : "ok",
        "version"  : "2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "llm"      : llm_status,
        "whisper"  : whisper_engine.model_size,
        "features" : {
            "memory_graph"   : _MEMORY_OK,
            "predictive_ai"  : _PREDICT_OK,
            "voice_stress"   : _STRESS_OK,
            "screen_reader"  : _SCREEN_OK,
            "biometric_auth" : _BIO_OK,
            "personality_ai" : _STYLE_OK,
            "parallel_agents": _PARALLEL_OK,
        }
    }


# ── Chat ─────────────────────────────────────────────────────

@app.post("/chat", tags=["Chat"])
async def chat(req: ChatRequest, db=Depends(get_db)):
    """
    Main chat endpoint with all v2 features.
    Key fix: stores ORIGINAL user text in DB, not the enriched version.
    """
    session = get_session(db, req.session_id)
    if not session:
        session = create_session(db, req.language)

    # Keep original text clean (for DB storage and display)
    original_text = req.text.strip()

    # 1. Gesture macro check
    if req.gesture and req.gesture not in ("NO GESTURE", "", "none", "NO_GESTURE"):
        if _PARALLEL_OK and command_processor.parallel_executor:
            try:
                macro_engine = GestureMacroEngine(db, command_processor.parallel_executor)
                macro_result = await macro_engine.trigger_gesture(
                    req.gesture, session.id, req.language
                )
                if macro_result:
                    response_text = f"⚡ Gesture macro '{macro_result['macro_name']}' triggered!"
                    add_message(db, session.id, role="user", content=original_text,
                               language=req.language, emotion=req.emotion)
                    add_message(db, session.id, role="assistant", content=response_text,
                               language=req.language, intent="gesture_macro",
                               action_data={"success": True, "macro": macro_result})
                    return {
                        "response": response_text,
                        "intent": "gesture_macro",
                        "action": macro_result,
                        "session_id": session.id,
                        "language": req.language,
                        "is_wake_word": False,
                        "suggestions": [],
                    }
            except Exception as e:
                print(f"[chat] Gesture macro: {e}")

    # 2. Memory context injection
    mem_context = ""
    if _MEMORY_OK and MemoryGraph:
        try:
            mem_context = MemoryGraph(db).get_context_for_prompt(original_text, max_memories=3)
        except Exception as e:
            print(f"[chat] Memory: {e}")

    # 3. Personality style
    style_prompt = ""
    if _STYLE_OK and PersonalityStyleEngine:
        try:
            se = PersonalityStyleEngine(db)
            se.learn_from_message(original_text, req.user_id, req.emotion, req.language)
            style_prompt = se.get_style_prompt_injection(req.user_id)
        except Exception as e:
            print(f"[chat] Style: {e}")

    # 4. Build enriched text (only sent to LLM, NOT stored in DB)
    enriched_parts = []
    if mem_context:
        enriched_parts.append(mem_context)
    if req.voice_stress > 60:
        enriched_parts.append(f"[Voice analysis: user sounds stressed ({req.voice_stress}/100). Be supportive.]")
    elif req.voice_stress > 40:
        enriched_parts.append(f"[Voice analysis: user sounds tense.]")

    enriched_text = original_text
    if enriched_parts:
        enriched_text = "\n".join(enriched_parts) + "\n\n" + original_text

    # 5. Parallel execution — ONLY for messages with 2+ real action intents
    # Skip if it looks conversational
    if _PARALLEL_OK and command_processor.parallel_executor:
        try:
            # Quick conversational check before expensive parallel detection
            original_lower = original_text.lower().strip()
            is_conversational = (
                len(original_text) < 30 or
                any(word in original_lower for word in [
                    "hi", "hello", "hey", "how are", "what's up",
                    "good morning", "good night", "thanks", "thank you",
                    "bye", "goodbye", "ok", "okay", "yes", "no", "sure"
                ])
            )

            if not is_conversational:
                intents = await command_processor.parallel_executor.detect_compound_intents(
                    original_text, req.language
                )
                # Only run parallel if 2+ REAL action intents (not conversational)
                real_intents = [
                    i for i in intents
                    if i.get("intent") not in CONVERSATIONAL_INTENTS
                ]

                if len(real_intents) >= 2:
                    parallel_result = await command_processor.parallel_executor.execute_compound(
                        original_text, session.id, req.language
                    )
                    if parallel_result.get("compound"):
                        response_text = parallel_result.get("summary", "Tasks completed.")
                        # Store clean text in DB
                        add_message(db, session.id, role="user", content=original_text,
                                   language=req.language, emotion=req.emotion)
                        add_message(db, session.id, role="assistant", content=response_text,
                                   language=req.language, intent="parallel_execution",
                                   action_data={"success": True, "parallel": True})
                        # Extract memories async
                        if _MEMORY_OK and MemoryGraph:
                            try:
                                asyncio.create_task(
                                    MemoryGraph(db).extract_and_store(
                                        original_text, response_text, session.id, req.emotion
                                    )
                                )
                            except Exception:
                                pass
                        return {
                            "response"      : response_text,
                            "intent"        : "parallel_execution",
                            "action"        : parallel_result,
                            "session_id"    : session.id,
                            "language"      : req.language,
                            "is_wake_word"  : False,
                            "parallel_tasks": parallel_result.get("tasks", []),
                            "suggestions"   : [],
                        }
        except Exception as e:
            print(f"[chat] Parallel detection: {e}")

    # 6. Normal processing — pass original_text so DB stores clean version
    result = await command_processor.process(
        text               = enriched_text,
        session_id         = session.id,
        language           = req.language,
        emotion            = req.emotion,
        db                 = db,
        style_prompt_extra = style_prompt,
        original_text      = original_text,  # Clean text for DB storage
    )

    # 7. Auto-extract memories
    if _MEMORY_OK and MemoryGraph and result.get("response"):
        try:
            asyncio.create_task(
                MemoryGraph(db).extract_and_store(
                    original_text, result["response"], session.id, req.emotion
                )
            )
        except Exception:
            pass

    # 8. Record usage pattern
    if _PREDICT_OK and PredictiveIntentEngine:
        try:
            intent = result.get("intent", "")
            if intent and intent not in CONVERSATIONAL_INTENTS:
                PredictiveIntentEngine(db).record_action(
                    intent    = intent,
                    params    = result.get("params", {}),
                    session_id= session.id,
                    emotion   = req.emotion,
                    success   = True,
                )
        except Exception:
            pass

    # 9. TTS for voice/hybrid
    if req.mode in ("voice", "hybrid") and result.get("response"):
        try:
            asyncio.create_task(tts_engine.speak_async(result["response"], req.language))
        except Exception:
            pass

    # 10. Get suggestions
    suggestions = []
    if _PREDICT_OK and PredictiveIntentEngine:
        try:
            suggestions = PredictiveIntentEngine(db).get_suggestions(req.emotion, top_k=2)
        except Exception:
            pass

    return {
        "response"    : result.get("response", ""),
        "intent"      : result.get("intent", ""),
        "action"      : result.get("action"),
        "session_id"  : session.id,
        "language"    : result.get("language", req.language),
        "is_wake_word": result.get("is_wake_word", False),
        "suggestions" : suggestions,
    }


# ── Transcribe ───────────────────────────────────────────────

@app.post("/transcribe", tags=["Speech"])
async def transcribe_audio(
    audio         : UploadFile = File(...),
    language      : str        = Form(default=""),
    format        : str        = Form(default="webm"),
    analyze_stress: bool       = Form(default=True),
):
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio")

        transcript    = await whisper_engine.transcribe(audio_bytes, language or None, format)
        stress_result = {}
        if analyze_stress and _STRESS_OK and voice_stress_analyzer:
            try:
                stress_result = await voice_stress_analyzer.analyze(audio_bytes, format)
            except Exception as e:
                print(f"[transcribe] Stress: {e}")

        return {**transcript, "voice_stress": stress_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── TTS ──────────────────────────────────────────────────────

@app.post("/tts", tags=["Speech"])
async def text_to_speech(req: TTSRequest):
    asyncio.create_task(tts_engine.speak_async(req.text, req.language))
    return {"status": "speaking"}

@app.post("/tts/stop", tags=["Speech"])
async def stop_tts():
    tts_engine.stop()
    return {"status": "stopped"}


# ── Sessions ─────────────────────────────────────────────────

@app.get("/sessions", tags=["Sessions"])
async def get_sessions(db=Depends(get_db)):
    try:
        sessions = list_sessions(db)
        result   = []
        for s in sessions:
            try:
                msg_count = db.execute(
                    sqlalchemy.text("SELECT COUNT(*) FROM messages WHERE session_id = :sid"),
                    {"sid": s.id}
                ).scalar() or 0
            except Exception:
                msg_count = 0
            result.append({
                "id"           : s.id,
                "title"        : s.title,
                "language"     : s.language,
                "is_active"    : s.is_active,
                "created_at"   : s.created_at.isoformat() if s.created_at else None,
                "updated_at"   : s.updated_at.isoformat() if s.updated_at else None,
                "message_count": msg_count,
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sessions", tags=["Sessions"])
async def new_session(req: SessionCreate, db=Depends(get_db)):
    s = create_session(db, req.language)
    return {"id":s.id,"title":s.title,"language":s.language,"is_active":s.is_active,"created_at":s.created_at.isoformat()}

@app.delete("/sessions/{session_id}", tags=["Sessions"])
async def remove_session(session_id: int, db=Depends(get_db)):
    try:
        db.execute(sqlalchemy.text("DELETE FROM messages WHERE session_id = :sid"), {"sid": session_id})
        db.execute(sqlalchemy.text("DELETE FROM sessions WHERE id = :sid"),         {"sid": session_id})
        db.commit()
        remaining = list_sessions(db)
        if remaining and not any(s.is_active for s in remaining):
            switch_session(db, remaining[0].id)
        return {"status": "deleted", "session_id": session_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sessions/{session_id}/switch", tags=["Sessions"])
async def activate_session(session_id: int, db=Depends(get_db)):
    s = switch_session(db, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "switched", "session_id": s.id, "title": s.title}

@app.get("/history/{session_id}", tags=["History"])
async def get_session_history(session_id: int, db=Depends(get_db)):
    s = get_session(db, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        messages = get_messages(db, session_id)
        return {
            "session_id": session_id,
            "title"     : s.title,
            "language"  : s.language,
            "messages"  : [
                {
                    "id"         : m.id,
                    "role"       : m.role,
                    "content"    : m.content,
                    "language"   : m.language,
                    "intent"     : m.intent,
                    "action_data": m.action_data,
                    "emotion"    : m.emotion,
                    "timestamp"  : m.timestamp.isoformat() if m.timestamp else None,
                }
                for m in messages
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Preferences ──────────────────────────────────────────────

@app.get("/preferences/{key}", tags=["Preferences"])
async def get_pref(key: str, db=Depends(get_db)):
    return {"key": key, "value": get_preference(db, key)}

@app.post("/preferences", tags=["Preferences"])
async def set_pref(req: PreferenceSet, db=Depends(get_db)):
    set_preference(db, req.key, req.value)
    return {"status": "saved", "key": req.key, "value": req.value}


# ── Memory ───────────────────────────────────────────────────

@app.post("/memory/store", tags=["Memory"])
async def store_memory(req: MemoryStoreRequest, db=Depends(get_db)):
    if not _MEMORY_OK:
        return {"success": False, "message": "Memory not available"}
    node = MemoryGraph(db).store(req.content, req.memory_type, req.tags, req.session_id, req.importance, "user")
    return {"success": True, "memory_id": node.id, "content": node.content}

@app.post("/memory/search", tags=["Memory"])
async def search_memory(req: MemorySearchRequest, db=Depends(get_db)):
    if not _MEMORY_OK:
        return {"results": [], "count": 0}
    results = MemoryGraph(db).search(req.query, req.top_k, req.memory_type)
    return {"results": results, "count": len(results)}

@app.get("/memory/all", tags=["Memory"])
async def get_all_memories(memory_type: Optional[str] = None, limit: int = 50, db=Depends(get_db)):
    if not _MEMORY_OK:
        return {"memories": [], "stats": {}}
    g = MemoryGraph(db)
    return {"memories": g.get_all(memory_type, limit), "stats": g.get_stats()}

@app.delete("/memory/{memory_id}", tags=["Memory"])
async def delete_memory(memory_id: int, db=Depends(get_db)):
    if not _MEMORY_OK or not MemoryGraph(db).delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True}

@app.get("/memory/stats", tags=["Memory"])
async def memory_stats(db=Depends(get_db)):
    if not _MEMORY_OK:
        return {"total_nodes": 0, "by_type": {}, "total_edges": 0}
    return MemoryGraph(db).get_stats()


# ── Predictive ────────────────────────────────────────────────

@app.get("/predict/suggestions", tags=["Predictive"])
async def get_suggestions(emotion: str = "neutral", db=Depends(get_db)):
    if not _PREDICT_OK:
        return {"suggestions": [], "analytics": {}}
    e = PredictiveIntentEngine(db)
    return {"suggestions": e.get_suggestions(emotion, top_k=3), "analytics": e.get_analytics()}


# ── Screen Reader ─────────────────────────────────────────────

@app.post("/screen/read", tags=["Vision"])
async def read_screen(question: str = Form(default="")):
    if not _SCREEN_OK:
        return {"success": False, "message": "Screen reader not available. Install pytesseract."}
    return await screen_reader.read_screen(question or None)

@app.post("/screen/answer", tags=["Vision"])
async def answer_screen(question: str = Form(...)):
    if not _SCREEN_OK:
        return {"success": False, "message": "Screen reader not available"}
    return await screen_reader.answer_about_screen(question)


# ── Voice Stress ──────────────────────────────────────────────

@app.post("/voice/analyze", tags=["Voice"])
async def analyze_voice(audio: UploadFile = File(...), format: str = Form(default="webm")):
    if not _STRESS_OK:
        return {"stress_level": 0, "voice_emotion": "neutral"}
    return await voice_stress_analyzer.analyze(await audio.read(), format)


# ── Biometric ─────────────────────────────────────────────────

@app.get("/auth/profiles", tags=["Auth"])
async def list_profiles():
    if not _BIO_OK:
        return {"profiles": [{"user_id": "default", "name": "User", "avatar": "👤"}], "active": {"user_id": "default"}}
    return {"profiles": biometric_auth.list_profiles(), "active": biometric_auth.active_profile}

@app.post("/auth/profiles", tags=["Auth"])
async def create_profile(req: ProfileCreate):
    if not _BIO_OK:
        return {"success": False, "message": "Biometric not available"}
    return {"success": True, "profile": biometric_auth.create_profile(req.name, req.avatar, req.user_id)}

@app.post("/auth/enroll", tags=["Auth"])
async def enroll_face(image: UploadFile = File(...), user_id: str = Form(...)):
    if not _BIO_OK:
        return {"success": False, "message": "Biometric not available"}
    img_bytes = await image.read()
    ext       = (image.filename or "face.jpg").split(".")[-1]
    return await biometric_auth.enroll_face(img_bytes, user_id, ext)

@app.post("/auth/recognize", tags=["Auth"])
async def recognize_face(image: UploadFile = File(...)):
    if not _BIO_OK:
        return {"recognized": False, "user_id": "default", "confidence": 0}
    img_bytes = await image.read()
    ext       = (image.filename or "face.jpg").split(".")[-1]
    return await biometric_auth.recognize_face(img_bytes, ext)

@app.post("/auth/switch/{user_id}", tags=["Auth"])
async def switch_profile(user_id: str):
    if not _BIO_OK:
        return {"success": False}
    return biometric_auth.switch_profile(user_id)

@app.delete("/auth/profiles/{user_id}", tags=["Auth"])
async def delete_profile(user_id: str):
    if not _BIO_OK:
        return {"success": False}
    return {"success": biometric_auth.delete_profile(user_id)}


# ── Personality ───────────────────────────────────────────────

@app.get("/personality/{user_id}", tags=["Personality"])
async def get_personality(user_id: str = "default", db=Depends(get_db)):
    if not _STYLE_OK:
        return {"profile": {}, "summary": "Style learning not available"}
    e = PersonalityStyleEngine(db)
    return {"profile": e.get_profile(user_id), "summary": e.get_profile_summary(user_id)}

@app.post("/personality/feedback", tags=["Personality"])
async def personality_feedback(req: StyleFeedback, db=Depends(get_db)):
    if not _STYLE_OK:
        return {"success": False}
    await PersonalityStyleEngine(db).learn_from_feedback("", req.feedback, 0, req.user_id)
    return {"success": True}


# ── Gesture Macros ────────────────────────────────────────────

@app.get("/macros", tags=["Macros"])
async def list_macros(db=Depends(get_db)):
    if not _PARALLEL_OK:
        return {"macros": []}
    return {"macros": GestureMacroEngine(db, None).list_macros()}

@app.post("/macros", tags=["Macros"])
async def create_macro(req: GestureMacroCreate, db=Depends(get_db)):
    from backend.db.models import GestureMacro
    macro = GestureMacro(gesture_name=req.gesture_name.upper(), macro_name=req.macro_name,
                         commands=json.dumps(req.commands), created_at=datetime.utcnow())
    db.add(macro); db.commit(); db.refresh(macro)
    return {"success": True, "macro_id": macro.id}

@app.delete("/macros/{macro_id}", tags=["Macros"])
async def delete_macro(macro_id: int, db=Depends(get_db)):
    if not _PARALLEL_OK:
        return {"success": False}
    return {"success": GestureMacroEngine(db, None).delete_macro(macro_id)}


# ── Direct Agent Endpoints ────────────────────────────────────

@app.post("/agent/screenshot", tags=["Agents"])
async def take_screenshot():
    from backend.agents.screen_agent import ScreenAgent
    return await ScreenAgent().take_screenshot({}, "direct")

@app.post("/agent/scrape", tags=["Agents"])
async def scrape_url(url: str = Form(...), summarize: bool = Form(default=False)):
    from backend.agents.web_agent import WebAgent
    return await WebAgent().scrape_url({"url": url, "extract": "all", "summarize": summarize}, "direct")

@app.post("/agent/analyze-data", tags=["Agents"])
async def analyze_data_file(file: UploadFile = File(...)):
    import tempfile
    suffix = os.path.splitext(file.filename or "data.csv")[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read()); tmp_path = tmp.name
    from backend.agents.data_agent import DataAgent
    result = await DataAgent().process_dataset({"file_path": tmp_path}, "direct")
    os.unlink(tmp_path)
    return result


# ── WebSockets ────────────────────────────────────────────────

@app.websocket("/ws/parallel")
async def parallel_ws(websocket: WebSocket):
    await websocket.accept()
    db = SessionLocal()
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", ""); session_id = data.get("session_id", 1); language = data.get("language", "en")
            if not text: continue
            async def send_status(d):
                try: await websocket.send_json(d)
                except: pass
            if _PARALLEL_OK and command_processor.parallel_executor:
                result = await command_processor.parallel_executor.execute_compound(text, session_id, language, send_status)
                await websocket.send_json({"event": "complete", "result": result})
    except WebSocketDisconnect:
        pass
    finally:
        db.close()

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    db = SessionLocal()
    try:
        while True:
            data = await websocket.receive_json()
            text=data.get("text",""); session_id=data.get("session_id",1); language=data.get("language","en"); emotion=data.get("emotion","neutral")
            if not text: continue
            result = await command_processor.process(text=text, session_id=session_id, language=language, emotion=emotion, db=db, original_text=text)
            await websocket.send_json({"response":result["response"],"intent":result["intent"],"action":result.get("action"),"is_wake_word":result.get("is_wake_word",False),"done":True})
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=APP_HOST, port=APP_PORT, reload=True)