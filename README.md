# ⬡ NEXON — Agentic AI Operating System

> Full-stack AI OS with voice, vision, gestures, and multi-agent automation.

---

## 🚀 Quick Start

### 1. Create the file structure
```bash
# Run the setup command from the project spec
# Then install dependencies:

cd nexon

# Backend
pip install -r requirements.txt
playwright install  # Optional: for web form automation

# Frontend
npm install
```

### 2. Start Ollama
```bash
# Install Ollama from https://ollama.com
ollama pull llama3.2:3b
ollama serve
```

### 3. Start the Python backend
```bash
cd nexon
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Start the Electron app (new terminal)
```bash
cd nexon
npm start

# Development mode (with DevTools):
npm run dev
```

---

## ⚙️ Configuration

Copy and edit `.env` in the `nexon/` root:

```env
# LLM
OLLAMA_MODEL=llama3.2:3b
LLM_PROVIDER=ollama
GROQ_API_KEY=          # Optional Groq fallback

# Speech
WHISPER_MODEL=base     # tiny | base | small | medium

# Email (Gmail example)
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587

# Messaging (optional)
TWILIO_SID=
TWILIO_TOKEN=
TWILIO_FROM=
SLACK_TOKEN=
```

---

## 📁 Project Structure
nexon/
├── backend/
│   ├── main.py              # FastAPI server (all endpoints)
│   ├── llm_engine.py        # Ollama + Groq LLM wrapper
│   ├── intent_parser.py     # Intent classification + entity extraction
│   ├── command_processor.py # Orchestrates agent pipeline
│   ├── config.py            # All configuration
│   ├── agents/              # 10 specialized AI agents
│   ├── speech/              # Whisper STT + pyttsx3 TTS
│   └── db/                  # SQLite ORM (sessions, messages)
├── frontend/
│   ├── electron/
│   │   ├── main.js          # Electron main process + IPC
│   │   └── preload.js       # Secure renderer bridge
│   └── renderer/
│       ├── index.html       # Full 3-column NEXON UI
│       ├── styles.css       # Futuristic dark theme
│       ├── renderer.js      # Main UI orchestrator
│       ├── sphere.js        # Three.js neural sphere
│       ├── waveform.js      # Audio waveform visualizer
│       ├── recorder.js      # Voice capture + VAD
│       └── camera.js        # Face mesh + gesture detection
├── requirements.txt
├── package.json
└── README.md


---

## 🎙️ Voice Commands (examples)

| Say | Action |
|-----|--------|
| "Hey NEXON, send email to john@example.com about the meeting" | Drafts + sends email |
| "Schedule a meeting tomorrow at 3pm" | Creates calendar event |
| "Take a screenshot" | Saves to ~/NEXON/Screenshots/ |
| "Search the web for Python tutorials" | DuckDuckGo search |
| "Open Chrome" | Launches application |
| "Summarize this file: /path/to/doc.pdf" | AI document summary |
| "Log expense $50 for lunch" | Finance tracking |
| "Set reminder: call mom at 6pm" | Creates reminder |

---

## 🌐 Language Modes

| Mode | Label | Description |
|------|-------|-------------|
| English | `EN` | Full English I/O |
| Hindi | `HI` | हिंदी में बातचीत |
| Hinglish | `MIX` | Mixed Hindi-English |

---

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Backend health + LLM status |
| POST | `/chat` | Main chat endpoint |
| POST | `/transcribe` | Audio → text (Whisper) |
| POST | `/tts` | Text → speech |
| GET | `/sessions` | List all sessions |
| POST | `/sessions` | Create new session |
| DELETE | `/sessions/{id}` | Delete session |
| GET | `/history/{id}` | Full message history |
| POST | `/agent/screenshot` | Take screenshot |
| POST | `/agent/scrape` | Scrape a URL |
| POST | `/agent/analyze-data` | Analyze uploaded CSV |

---

## 🛠️ Troubleshooting

**"Cannot connect to Ollama"**
→ Run `ollama serve` in a separate terminal.

**Whisper takes too long**
→ Change `WHISPER_MODEL=tiny` in `.env` for faster (less accurate) transcription.

**Camera not showing**
→ Allow camera permissions in Electron settings or system privacy settings.

**Email not sending**
→ For Gmail, use an App Password (not your main password).
   Enable 2FA → Google Account → Security → App Passwords.

**MediaPipe not loading**
→ Requires internet connection on first launch (CDN scripts).
   After that, serve locally or bundle with electron-builder.
