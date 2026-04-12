# backend/config.py
# ============================================================
# NEXON Configuration
# Central config for all backend modules.
# Edit OLLAMA_MODEL and GROQ_API_KEY here or in .env file.
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ----------------------------
# LLM Configuration
# ----------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")          # Optional fallback
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama3-70b-8192")

# Which engine to use: "ollama" | "groq"
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "ollama")

# ----------------------------
# Database
# ----------------------------
DB_PATH         = os.getenv("DB_PATH", "nexon.db")
DB_URL          = f"sqlite:///{DB_PATH}"

# ----------------------------
# Speech
# ----------------------------
WHISPER_MODEL   = os.getenv("WHISPER_MODEL", "base")     # tiny|base|small|medium
TTS_RATE        = int(os.getenv("TTS_RATE", "175"))       # words per minute
TTS_VOLUME      = float(os.getenv("TTS_VOLUME", "1.0"))

# ----------------------------
# Paths
# ----------------------------
NEXON_HOME      = os.path.expanduser("~/NEXON")
SCREENSHOT_DIR  = os.path.join(NEXON_HOME, "Screenshots")
RECORDINGS_DIR  = os.path.join(NEXON_HOME, "Recordings")
DOCUMENTS_DIR   = os.path.join(NEXON_HOME, "Documents")
DOWNLOADS_DIR   = os.path.join(NEXON_HOME, "Downloads")

# Create directories on startup
for _dir in [NEXON_HOME, SCREENSHOT_DIR, RECORDINGS_DIR, DOCUMENTS_DIR, DOWNLOADS_DIR]:
    os.makedirs(_dir, exist_ok=True)

# ----------------------------
# Memory
# ----------------------------
MAX_CONTEXT_MESSAGES = 10   # How many recent messages to include in LLM context
SUMMARY_THRESHOLD    = 20   # Summarize older messages after this count

# ----------------------------
# Email (fill in or use .env)
# ----------------------------
EMAIL_ADDRESS   = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD  = os.getenv("EMAIL_PASSWORD", "")
SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))

# ----------------------------
# Messaging APIs (optional)
# ----------------------------
TWILIO_SID      = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN    = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM     = os.getenv("TWILIO_FROM", "")
SLACK_TOKEN     = os.getenv("SLACK_TOKEN", "")

# ----------------------------
# App settings
# ----------------------------
APP_HOST        = "127.0.0.1"
APP_PORT        = 8000
CORS_ORIGINS    = ["*"]     # Electron renderer uses file:// origin