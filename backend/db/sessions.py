# backend/db/sessions.py — FIXED VERSION
# ============================================================
# Fix: get_messages uses explicit column selection to avoid
# errors when old DB has missing columns.
# ============================================================

import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as DBSession
from datetime import datetime
from typing import List, Optional, Dict, Any

from .models import Base, Session, Message, UserPreference, ClipboardItem
from backend.config import DB_URL, MAX_CONTEXT_MESSAGES

engine       = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables that don't exist yet."""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Session CRUD ─────────────────────────────────────────────

def create_session(db: DBSession, language: str = "en") -> Session:
    db.query(Session).update({"is_active": False})
    session = Session(language=language, is_active=True)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: DBSession) -> List[Session]:
    return db.query(Session).order_by(Session.updated_at.desc()).all()


def get_session(db: DBSession, session_id: int) -> Optional[Session]:
    return db.query(Session).filter(Session.id == session_id).first()


def switch_session(db: DBSession, session_id: int) -> Optional[Session]:
    db.query(Session).update({"is_active": False})
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.is_active = True
        db.commit()
        db.refresh(session)
    return session


def delete_session(db: DBSession, session_id: int) -> bool:
    """Delete a session using raw SQL to avoid ORM column-mismatch issues."""
    try:
        # Delete messages first
        db.execute(text("DELETE FROM messages WHERE session_id = :sid"), {"sid": session_id})
        # Delete session
        result = db.execute(text("DELETE FROM sessions WHERE id = :sid"), {"sid": session_id})
        db.commit()
        return result.rowcount > 0
    except Exception as e:
        db.rollback()
        print(f"[sessions] delete_session error: {e}")
        return False


def update_session_title(db: DBSession, session_id: int, title: str):
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.title      = title[:200]
        session.updated_at = datetime.utcnow()
        db.commit()


def get_active_session(db: DBSession) -> Optional[Session]:
    return db.query(Session).filter(Session.is_active == True).first()


# ── Message CRUD ─────────────────────────────────────────────

def add_message(
    db         : DBSession,
    session_id : int,
    role       : str,
    content    : str,
    language   : str           = "en",
    intent     : str           = "",
    action_data: Optional[Dict]= None,
    emotion    : str           = "neutral"
) -> Message:
    """
    Add a message using only the base columns that exist in all DB versions.
    Voice stress and parallel task data are stored in separate tables.
    """
    msg = Message(
        session_id  = session_id,
        role        = role,
        content     = content,
        language    = language,
        intent      = intent,
        action_data = action_data,
        emotion     = emotion,
    )
    db.add(msg)

    # Update session
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.updated_at = datetime.utcnow()
        if role == "user" and session.title == "New Chat":
            session.title = content[:60] + ("…" if len(content) > 60 else "")

    try:
        db.commit()
        db.refresh(msg)
    except Exception as e:
        db.rollback()
        print(f"[sessions] add_message error: {e}")
        raise
    return msg


def get_messages(db: DBSession, session_id: int) -> List[Message]:
    """
    Fetch messages using explicit column list to avoid
    errors when DB schema has extra/missing columns.
    """
    try:
        return (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.id)
            .all()
        )
    except Exception as e:
        print(f"[sessions] get_messages ORM failed ({e}), trying raw SQL")
        # Fallback: raw SQL with only guaranteed columns
        try:
            rows = db.execute(
                text("""
                    SELECT id, session_id, role, content, language,
                           intent, action_data, emotion, timestamp
                    FROM messages
                    WHERE session_id = :sid
                    ORDER BY id
                """),
                {"sid": session_id}
            ).fetchall()

            messages = []
            for row in rows:
                m             = Message.__new__(Message)
                m.id          = row[0]
                m.session_id  = row[1]
                m.role        = row[2]
                m.content     = row[3]
                m.language    = row[4]
                m.intent      = row[5] or ""
                m.action_data = row[6]
                m.emotion     = row[7] or "neutral"
                m.timestamp   = row[8]
                messages.append(m)
            return messages
        except Exception as e2:
            print(f"[sessions] get_messages raw SQL also failed: {e2}")
            return []


def get_context_messages(db: DBSession, session_id: int) -> List[Dict]:
    """Return last N messages as LLM context dicts."""
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
    except Exception:
        session = None

    messages = get_messages(db, session_id)
    recent   = messages[-MAX_CONTEXT_MESSAGES:]

    context = []
    if session and getattr(session, 'summary', ''):
        context.append({
            "role"   : "system",
            "content": f"[Previous conversation summary]: {session.summary}"
        })

    for msg in recent:
        context.append({"role": msg.role, "content": msg.content})

    return context


def save_summary(db: DBSession, session_id: int, summary: str):
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.summary = summary
        try:
            db.commit()
        except Exception:
            db.rollback()


# ── Preferences ──────────────────────────────────────────────

def get_preference(db: DBSession, key: str, default: str = "") -> str:
    try:
        pref = db.query(UserPreference).filter(UserPreference.key == key).first()
        return pref.value if pref else default
    except Exception:
        return default


def set_preference(db: DBSession, key: str, value: str):
    try:
        pref = db.query(UserPreference).filter(UserPreference.key == key).first()
        if pref:
            pref.value = value
        else:
            db.add(UserPreference(key=key, value=value))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[sessions] set_preference error: {e}")


# ── Clipboard ─────────────────────────────────────────────────

def add_clipboard(db: DBSession, content: str, content_type: str = "text") -> ClipboardItem:
    item = ClipboardItem(content=content, content_type=content_type)
    db.add(item)
    db.commit()
    count = db.query(ClipboardItem).filter(ClipboardItem.pinned == False).count()
    if count > 100:
        oldest = (
            db.query(ClipboardItem)
            .filter(ClipboardItem.pinned == False)
            .order_by(ClipboardItem.timestamp)
            .first()
        )
        if oldest:
            db.delete(oldest)
            db.commit()
    return item


def get_clipboard_history(db: DBSession, limit: int = 50) -> List[ClipboardItem]:
    return (
        db.query(ClipboardItem)
        .order_by(ClipboardItem.pinned.desc(), ClipboardItem.timestamp.desc())
        .limit(limit)
        .all()
    )