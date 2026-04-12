# backend/voice/stress_analyzer.py
# ============================================================
# NEXON Voice Stress & Emotion Analyzer
# Analyzes audio spectral features to detect:
#   - Stress level (0-100)
#   - Confidence level
#   - Speech rate (fast/normal/slow)
#   - Energy level
#   - Overall voice emotion
#
# Uses: numpy + librosa (pip install librosa)
# Falls back to basic energy analysis if librosa not available.
# ============================================================

import io
import math
import tempfile
import os
from typing import Dict, Optional

import numpy as np

# Try librosa for full analysis
_LIBROSA = False
try:
    import librosa
    _LIBROSA = True
    print("[VoiceStress] librosa loaded ✓")
except ImportError:
    print("[VoiceStress] librosa not found — using basic analysis")


class VoiceStressAnalyzer:
    """
    Analyzes audio features to determine emotional/stress state of the speaker.

    Features analyzed:
    - Pitch (F0): High variance = excited/stressed
    - Energy (RMS): High = excited/angry, Low = sad/tired
    - Speech rate: Fast = excited/stressed, Slow = sad/bored
    - Spectral centroid: Brightness of voice
    - Zero crossing rate: Noisiness

    All processing is LOCAL — no audio sent to any cloud.
    """

    def __init__(self):
        self.sample_rate = 16000  # Whisper's preferred SR

    async def analyze(self, audio_bytes: bytes, audio_format: str = "webm") -> Dict:
        """
        Analyze audio bytes for stress and emotion features.

        Args:
            audio_bytes  : Raw audio data.
            audio_format : File format hint.
        Returns:
            Dict with keys:
                stress_level   (int)  : 0-100 stress score
                confidence     (int)  : 0-100 confidence score
                energy_level   (str)  : 'low' | 'normal' | 'high'
                speech_rate    (str)  : 'slow' | 'normal' | 'fast'
                voice_emotion  (str)  : 'calm' | 'stressed' | 'excited' | 'sad' | 'angry' | 'confident'
                pitch_variance (float): Pitch variability (higher = more emotional)
                details        (dict) : Raw feature values
        """
        # Write to temp file for librosa
        suffix = f".{audio_format}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            if _LIBROSA:
                return await self._analyze_librosa(tmp_path)
            else:
                return await self._analyze_basic(audio_bytes)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def _analyze_librosa(self, audio_path: str) -> Dict:
        """Full spectral analysis using librosa."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._librosa_sync, audio_path)

    def _librosa_sync(self, audio_path: str) -> Dict:
        """Synchronous librosa analysis (run in thread pool)."""
        try:
            # Load audio
            y, sr = librosa.load(audio_path, sr=self.sample_rate, mono=True)

            if len(y) < 1024:
                return self._default_result()

            # ── Feature extraction ─────────────────────────

            # 1. Pitch (F0) using piptrack
            pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
            pitch_values = []
            for t in range(pitches.shape[1]):
                idx = magnitudes[:, t].argmax()
                pitch = pitches[idx, t]
                if pitch > 50:  # Filter noise
                    pitch_values.append(float(pitch))

            pitch_mean    = np.mean(pitch_values) if pitch_values else 150.0
            pitch_std     = np.std(pitch_values)  if pitch_values else 20.0
            pitch_variance= float(pitch_std / (pitch_mean + 1e-6))

            # 2. Energy (RMS)
            rms          = librosa.feature.rms(y=y)[0]
            energy_mean  = float(np.mean(rms))
            energy_max   = float(np.max(rms))

            # 3. Speech rate estimate via onsets
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
            duration_sec = len(y) / sr
            speech_rate  = len(onset_frames) / max(duration_sec, 0.1)  # onsets/sec

            # 4. Spectral centroid (brightness)
            centroid     = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            centroid_mean= float(np.mean(centroid))

            # 5. Zero crossing rate (noisiness)
            zcr          = librosa.feature.zero_crossing_rate(y)[0]
            zcr_mean     = float(np.mean(zcr))

            # 6. MFCC for timbre
            mfccs        = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_mean    = float(np.mean(mfccs[1]))  # 2nd MFCC for vocal tract

            # ── Scoring ────────────────────────────────────

            # Stress: high pitch variance + high energy + fast speech rate
            stress_score = (
                min(100, pitch_variance * 200) * 0.35 +
                min(100, energy_mean   * 5000) * 0.30 +
                min(100, speech_rate   * 6)    * 0.20 +
                min(100, zcr_mean      * 500)  * 0.15
            )
            stress_level = int(min(100, max(0, stress_score)))

            # Confidence: steady pitch + good energy + moderate speed
            pitch_steadiness  = max(0, 1 - pitch_variance * 3)
            energy_adequacy   = min(1, energy_mean * 3000)
            speed_appropriateness = 1 - abs(speech_rate - 4) / 8
            confidence_score  = (pitch_steadiness * 0.4 + energy_adequacy * 0.4 + speed_appropriateness * 0.2)
            confidence_level  = int(min(100, max(0, confidence_score * 100)))

            # Energy label
            if energy_mean < 0.02:
                energy_label = "low"
            elif energy_mean < 0.08:
                energy_label = "normal"
            else:
                energy_label = "high"

            # Speech rate label
            if speech_rate < 2.5:
                rate_label = "slow"
            elif speech_rate < 6.0:
                rate_label = "normal"
            else:
                rate_label = "fast"

            # Voice emotion classification
            voice_emotion = self._classify_emotion(
                stress_level, confidence_level, energy_label, rate_label, pitch_variance
            )

            return {
                "stress_level"  : stress_level,
                "confidence"    : confidence_level,
                "energy_level"  : energy_label,
                "speech_rate"   : rate_label,
                "voice_emotion" : voice_emotion,
                "pitch_variance": round(pitch_variance, 4),
                "details": {
                    "pitch_mean"    : round(pitch_mean, 1),
                    "pitch_std"     : round(pitch_std, 1),
                    "energy_mean"   : round(energy_mean, 5),
                    "speech_rate_hz": round(speech_rate, 2),
                    "centroid_hz"   : round(centroid_mean, 1),
                    "zcr"           : round(zcr_mean, 5),
                    "duration_sec"  : round(duration_sec, 2),
                }
            }

        except Exception as e:
            print(f"[VoiceStress] librosa analysis error: {e}")
            return self._default_result()

    async def _analyze_basic(self, audio_bytes: bytes) -> Dict:
        """
        Basic energy-only analysis fallback (no librosa).
        Works with raw PCM bytes.
        """
        try:
            # Try to parse as 16-bit PCM
            import array
            pcm = array.array('h')
            # Skip potential header bytes
            data = audio_bytes[44:] if len(audio_bytes) > 44 else audio_bytes
            if len(data) % 2 != 0:
                data = data[:-1]
            pcm.frombytes(data)

            if not pcm:
                return self._default_result()

            samples = np.array(pcm, dtype=np.float32) / 32768.0
            energy  = float(np.sqrt(np.mean(samples ** 2)))

            stress     = int(min(100, energy * 300))
            confidence = int(min(100, 50 + energy * 200))

            return {
                "stress_level"  : stress,
                "confidence"    : confidence,
                "energy_level"  : "high" if energy > 0.1 else "normal" if energy > 0.03 else "low",
                "speech_rate"   : "normal",
                "voice_emotion" : "stressed" if stress > 60 else "calm",
                "pitch_variance": 0.0,
                "details"       : {"energy_rms": round(energy, 5)}
            }
        except Exception:
            return self._default_result()

    def _classify_emotion(
        self, stress: int, confidence: int,
        energy: str, rate: str, pitch_var: float
    ) -> str:
        """Rule-based voice emotion classification."""
        if stress > 70 and energy == "high" and rate == "fast":
            return "stressed"
        if stress > 60 and energy == "high":
            return "angry"
        if confidence > 70 and energy in ("normal", "high") and rate == "normal":
            return "confident"
        if stress < 30 and energy == "low" and rate == "slow":
            return "sad"
        if pitch_var > 0.3 and rate == "fast" and energy == "high":
            return "excited"
        if stress < 40 and confidence > 50:
            return "calm"
        return "neutral"

    def _default_result(self) -> Dict:
        return {
            "stress_level"  : 0,
            "confidence"    : 50,
            "energy_level"  : "normal",
            "speech_rate"   : "normal",
            "voice_emotion" : "neutral",
            "pitch_variance": 0.0,
            "details"       : {}
        }


# Singleton
voice_stress_analyzer = VoiceStressAnalyzer()