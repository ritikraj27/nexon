# backend/speech/whisper_engine.py — FIXED VERSION
# ============================================================
# Fixes:
# 1. Accepts WAV format natively (no ffmpeg conversion needed)
# 2. Uses 'tiny' model by default (4x faster than 'base')
#    Change WHISPER_MODEL=base in .env for better accuracy
# 3. Better error handling for corrupted audio
# 4. fp16=False for CPU/Metal compatibility
# ============================================================

import os
import io
import wave
import tempfile
import asyncio
import struct
from typing import Optional, Dict
from backend.config import WHISPER_MODEL, TTS_RATE, TTS_VOLUME

# Lazy-load whisper (takes a few seconds)
_whisper_module = None
_whisper_model  = None

def _get_whisper():
    global _whisper_module, _whisper_model
    if _whisper_model is None:
        import whisper as _w
        _whisper_module = _w
        print(f"[WhisperEngine] Loading '{WHISPER_MODEL}' model...")
        _whisper_model = _w.load_model(WHISPER_MODEL)
        print("[WhisperEngine] Model loaded successfully.")
    return _whisper_model

# Wake words in multiple languages
WAKE_WORDS = [
    "hey nexon", "hi nexon", "hello nexon",
    "oye nexon", "ok nexon", "okay nexon",
    "नमस्ते नेक्सन", "हाय नेक्सन", "हेलो नेक्सन",
    "nexon",
]


class WhisperEngine:
    """
    Local Whisper STT engine.
    Accepts WAV (preferred) or WebM audio.
    Uses tiny model by default for <2 second response time.
    """

    def __init__(self, model_size: str = WHISPER_MODEL):
        self.model_size = model_size
        self._lock      = asyncio.Lock()

    async def transcribe(
        self,
        audio_bytes  : bytes,
        language     : Optional[str] = None,
        audio_format : str = "wav"
    ) -> Dict:
        """
        Transcribe audio bytes to text.

        Args:
            audio_bytes  : Raw audio (WAV preferred, WebM accepted)
            language     : Force language code or None for auto-detect
            audio_format : 'wav' or 'webm'
        Returns:
            {text, language, confidence, is_wake_word, wake_word}
        """
        async with self._lock:
            loop = asyncio.get_event_loop()

            # Load model on first call
            await loop.run_in_executor(None, _get_whisper)

            # Validate audio
            if not audio_bytes or len(audio_bytes) < 100:
                return self._empty_result("Audio too short or empty")

            # Write to temp file with correct extension
            suffix = ".wav" if audio_format == "wav" else ".webm"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                result = await loop.run_in_executor(
                    None,
                    self._transcribe_sync,
                    tmp_path,
                    language,
                    audio_format,
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            return result

    def _transcribe_sync(self, audio_path: str, language: Optional[str], audio_format: str) -> Dict:
        """Synchronous Whisper transcription (CPU-bound, runs in thread pool)."""
        model = _get_whisper()

        options = {
            "fp16"   : False,    # CPU/Metal safe
            "verbose": False,
            "task"   : "transcribe",
        }

        if language and language not in ("hinglish", ""):
            options["language"] = language

        try:
            result = model.transcribe(audio_path, **options)
        except Exception as e:
            error_str = str(e)
            if "EBML" in error_str or "Invalid data" in error_str or "Failed to load" in error_str:
                return self._empty_result(f"Audio format error: {error_str[:100]}")
            raise

        text     = result.get("text", "").strip()
        detected = result.get("language", "en")

        # Confidence from segments
        segments = result.get("segments", [])
        if segments:
            avg_lp     = sum(s.get("avg_logprob", -1) for s in segments) / len(segments)
            confidence = max(0.0, min(1.0, avg_lp + 1.0))
        else:
            confidence = 0.5

        # Wake word check
        text_lower    = text.lower()
        detected_wake = next((w for w in WAKE_WORDS if w in text_lower), None)

        return {
            "text"        : text,
            "language"    : detected,
            "confidence"  : round(confidence, 3),
            "is_wake_word": detected_wake is not None,
            "wake_word"   : detected_wake or "",
        }

    def _empty_result(self, reason: str = "") -> Dict:
        if reason:
            print(f"[WhisperEngine] Empty result: {reason}")
        return {
            "text"        : "",
            "language"    : "en",
            "confidence"  : 0.0,
            "is_wake_word": False,
            "wake_word"   : "",
        }


# ── TTS Engine ────────────────────────────────────────────────

class TTSEngine:
    """pyttsx3-based TTS (fallback — frontend uses Web Speech API)."""

    def __init__(self):
        self._engine = None
        import threading
        self._lock = threading.Lock()

    def _get_engine(self):
        if self._engine is None:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate",   TTS_RATE)
                self._engine.setProperty("volume", TTS_VOLUME)
            except Exception as e:
                print(f"[TTS] pyttsx3 init failed: {e}")
        return self._engine

    def speak(self, text: str, language: str = "en"):
        with self._lock:
            engine = self._get_engine()
            if not engine:
                return
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"[TTS] speak error: {e}")

    async def speak_async(self, text: str, language: str = "en"):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.speak, text, language)

    def stop(self):
        with self._lock:
            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass


# Singletons
whisper_engine = WhisperEngine()
tts_engine     = TTSEngine()