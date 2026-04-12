# backend/db/models.py — FIXED VERSION
# ============================================================
# Key fix: Message model no longer has voice_stress/voice_emotion/
# parallel_tasks columns (they live in separate tables).
# This prevents "no such column" errors on existing databases.
# All new tables are created fresh by init_db().
# ============================================================

from sqlalchemy import (
    Column, Integer, String, Text, Float,
    DateTime, Boolean, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


# ── Core Tables ──────────────────────────────────────────────

class Session(Base):
    """Chat session / conversation thread."""
    __tablename__ = "sessions"

    id         = Column(Integer, primary_key=True, index=True)
    title      = Column(String(200), default="New Chat")
    language   = Column(String(20),  default="en")
    created_at = Column(DateTime,    default=datetime.utcnow)
    updated_at = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)
    summary    = Column(Text,        default="")
    is_active  = Column(Boolean,     default=False)

    messages   = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.id",
        lazy="select"
    )


class Message(Base):
    """Single message in a chat session."""
    __tablename__ = "messages"

    id          = Column(Integer, primary_key=True, index=True)
    session_id  = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    role        = Column(String(20),  nullable=False)   # 'user' | 'assistant'
    content     = Column(Text,        nullable=False)
    language    = Column(String(20),  default="en")
    intent      = Column(String(100), default="")
    action_data = Column(JSON,        default=None)
    emotion     = Column(String(50),  default="neutral")
    timestamp   = Column(DateTime,    default=datetime.utcnow)
    # NOTE: voice_stress, voice_emotion, parallel_tasks removed from here
    # They live in VoiceAnalysis table to avoid migration issues.

    session     = relationship("Session", back_populates="messages")


class UserPreference(Base):
    """Persistent user preferences (key-value store)."""
    __tablename__ = "preferences"

    id    = Column(Integer, primary_key=True)
    key   = Column(String(100), unique=True, nullable=False)
    value = Column(Text, default="")


class ClipboardItem(Base):
    """Clipboard history — last 100 entries."""
    __tablename__ = "clipboard"

    id           = Column(Integer, primary_key=True)
    content      = Column(Text,       nullable=False)
    content_type = Column(String(50), default="text")
    timestamp    = Column(DateTime,   default=datetime.utcnow)
    pinned       = Column(Boolean,    default=False)


# ── Long-term Memory Graph ───────────────────────────────────

class MemoryNode(Base):
    """A single memory fact/event with semantic embedding."""
    __tablename__ = "memory_nodes"

    id           = Column(Integer, primary_key=True, index=True)
    content      = Column(Text,        nullable=False)
    memory_type  = Column(String(50),  default="fact")
    tags         = Column(Text,        default="[]")
    session_id   = Column(Integer,     nullable=True)
    importance   = Column(Float,       default=0.5)
    source       = Column(String(50),  default="user")
    embedding    = Column(Text,        nullable=True)
    created_at   = Column(DateTime,    default=datetime.utcnow)
    last_accessed= Column(DateTime,    default=datetime.utcnow)
    access_count = Column(Integer,     default=0)

    edges_from   = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.from_node_id",
        back_populates="from_node",
        cascade="all, delete-orphan"
    )
    edges_to     = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.to_node_id",
        back_populates="to_node"
    )


class MemoryEdge(Base):
    """Directed edge connecting two memory nodes."""
    __tablename__ = "memory_edges"

    id           = Column(Integer, primary_key=True)
    from_node_id = Column(Integer, ForeignKey("memory_nodes.id"), nullable=False)
    to_node_id   = Column(Integer, ForeignKey("memory_nodes.id"), nullable=False)
    weight       = Column(Float,      default=0.5)
    edge_type    = Column(String(50), default="similar")
    created_at   = Column(DateTime,   default=datetime.utcnow)

    from_node    = relationship("MemoryNode", foreign_keys=[from_node_id], back_populates="edges_from")
    to_node      = relationship("MemoryNode", foreign_keys=[to_node_id],   back_populates="edges_to")


# ── Predictive Intent Patterns ───────────────────────────────

class UsagePattern(Base):
    """Learned usage patterns for predictive suggestions."""
    __tablename__ = "usage_patterns"

    id            = Column(Integer, primary_key=True)
    pattern_key   = Column(String(200), unique=True, index=True, nullable=False)
    intent        = Column(String(100), nullable=False)
    params_sample = Column(Text,        default="{}")
    emotion       = Column(String(50),  default="neutral")
    day_of_week   = Column(String(20),  default="")
    hour_of_day   = Column(Integer,     default=0)
    count         = Column(Integer,     default=1)
    success_count = Column(Integer,     default=0)
    first_seen    = Column(DateTime,    default=datetime.utcnow)
    last_seen     = Column(DateTime,    default=datetime.utcnow)


# ── Personality Profiles ─────────────────────────────────────

class PersonalityProfile(Base):
    """Learned communication style per user."""
    __tablename__ = "personality_profiles"

    id           = Column(Integer, primary_key=True)
    user_id      = Column(String(100), unique=True, index=True, nullable=False)
    profile_json = Column(Text, default="{}")
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Gesture Macros ───────────────────────────────────────────

class GestureMacro(Base):
    """User-defined gesture → command sequence mappings."""
    __tablename__ = "gesture_macros"

    id           = Column(Integer, primary_key=True)
    gesture_name = Column(String(100), index=True, nullable=False)
    macro_name   = Column(String(200), nullable=False)
    commands     = Column(Text, default="[]")
    created_at   = Column(DateTime, default=datetime.utcnow)
    run_count    = Column(Integer,  default=0)
    last_run     = Column(DateTime, nullable=True)
    is_active    = Column(Boolean,  default=True)


# ── Voice Analysis ───────────────────────────────────────────

class VoiceAnalysis(Base):
    """Voice stress/emotion analysis results (separate from messages)."""
    __tablename__ = "voice_analysis"

    id            = Column(Integer, primary_key=True)
    message_id    = Column(Integer, nullable=True)
    session_id    = Column(Integer, nullable=True)
    stress_level  = Column(Integer, default=0)
    confidence    = Column(Integer, default=50)
    energy_level  = Column(String(20), default="normal")
    speech_rate   = Column(String(20), default="normal")
    voice_emotion = Column(String(50), default="neutral")
    pitch_variance= Column(Float,   default=0.0)
    details_json  = Column(Text,    default="{}")
    created_at    = Column(DateTime, default=datetime.utcnow)