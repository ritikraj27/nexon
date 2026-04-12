// frontend/renderer/tts_engine.js
// ============================================================
// NEXON Human Voice TTS Engine
// Uses Web Speech API with:
// - Female voice preference (Samantha on macOS, Google UK Female, etc.)
// - Emotion-aware rate, pitch, and volume
// - Wake word listening in background
// - Smooth sentence-by-sentence delivery
// ============================================================

class NexonTTSEngine {
  constructor() {
    this.synth         = window.speechSynthesis;
    this.voices        = [];
    this.preferredVoice= null;
    this.isSpeaking    = false;
    this.currentEmotion= 'neutral';
    this.queue         = [];
    this._loadVoices();

    // Wake word listening state
    this._wakeRecognizer = null;
    this._wakeListening  = false;
    this._onWakeWord     = null;

    // Reload voices when they become available (Chrome loads async)
    if (this.synth.onvoiceschanged !== undefined) {
      this.synth.onvoiceschanged = () => this._loadVoices();
    }
  }

  // ── Voice Loading ─────────────────────────────────────────

  _loadVoices() {
    this.voices = this.synth.getVoices();
    this.preferredVoice = this._selectBestVoice();
    if (this.preferredVoice) {
      console.log(`[TTS] Using voice: ${this.preferredVoice.name} (${this.preferredVoice.lang})`);
    }
  }

  _selectBestVoice() {
    const voices = this.voices;
    if (!voices.length) return null;

    // Priority list of preferred female voices (best quality first)
    const preferred = [
      // macOS premium voices
      'Samantha',         // macOS default female — best quality
      'Karen',            // Australian female
      'Moira',            // Irish female
      'Tessa',            // South African female
      'Veena',            // Indian English female
      // Chrome/Google voices
      'Google UK English Female',
      'Google US English',
      // Windows voices
      'Microsoft Aria Online (Natural)',
      'Microsoft Jenny Online (Natural)',
      'Microsoft Zira Desktop',
      // Generic fallbacks
      'en-GB-Neural2-C',
      'en-US-Neural2-F',
    ];

    for (const name of preferred) {
      const v = voices.find(v => v.name.includes(name));
      if (v) return v;
    }

    // Fallback: any female-sounding English voice
    const femaleKeywords = ['female', 'woman', 'girl', 'she', 'karen', 'samantha', 'aria', 'jenny', 'zira', 'moira', 'tessa', 'veena', 'victoria'];
    for (const kw of femaleKeywords) {
      const v = voices.find(v => v.name.toLowerCase().includes(kw) && v.lang.startsWith('en'));
      if (v) return v;
    }

    // Last resort: first English voice
    return voices.find(v => v.lang.startsWith('en')) || voices[0];
  }

  // ── Emotion-aware speech parameters ──────────────────────

  _getEmotionParams(emotion) {
    const params = {
      neutral  : { rate: 1.0,  pitch: 1.0,  volume: 1.0,  pauseMs: 0    },
      happy    : { rate: 1.1,  pitch: 1.15, volume: 1.0,  pauseMs: 0    },
      sad      : { rate: 0.85, pitch: 0.88, volume: 0.9,  pauseMs: 100  },
      angry    : { rate: 1.05, pitch: 0.95, volume: 1.0,  pauseMs: 0    },
      surprised: { rate: 1.1,  pitch: 1.2,  volume: 1.0,  pauseMs: 0    },
      fearful  : { rate: 1.05, pitch: 1.05, volume: 0.95, pauseMs: 50   },
      disgusted: { rate: 0.92, pitch: 0.92, volume: 0.95, pauseMs: 50   },
      stressed : { rate: 1.08, pitch: 1.05, volume: 0.95, pauseMs: 0    },
      excited  : { rate: 1.15, pitch: 1.18, volume: 1.0,  pauseMs: 0    },
      calm     : { rate: 0.92, pitch: 0.95, volume: 0.9,  pauseMs: 80   },
    };
    return params[emotion?.toLowerCase()] || params.neutral;
  }

  // ── Main speak function ───────────────────────────────────

  speak(text, options = {}) {
    if (!text?.trim() || !this.synth) return;

    const {
      language = 'en',
      emotion  = this.currentEmotion || 'neutral',
      onStart  = null,
      onEnd    = null,
      priority = false,
    } = options;

    // Cancel current speech if priority
    if (priority) this.stop();

    // Clean text for TTS
    const clean = this._cleanText(text);
    if (!clean) return;

    // Split into sentences for more natural delivery
    const sentences = this._splitIntoSentences(clean);
    if (!sentences.length) return;

    const params = this._getEmotionParams(emotion);

    // Select voice — prefer language-appropriate voice
    const voice = (language === 'hi')
      ? this.voices.find(v => v.lang.startsWith('hi')) || this.preferredVoice
      : this.preferredVoice;

    this.isSpeaking = true;
    if (onStart) onStart();

    // Notify UI
    if (window.nexonWaveform) window.nexonWaveform.setMode('assistant');
    if (window.nexonSphere)   window.nexonSphere.setState('assistant');
    if (window.nexonAvatar)   window.nexonAvatar.startTalking();

    // Speak sentences sequentially
    let idx = 0;
    const speakNext = () => {
      if (idx >= sentences.length) {
        this.isSpeaking = false;
        if (onEnd) onEnd();
        if (window.nexonWaveform) window.nexonWaveform.setMode('idle');
        if (window.nexonSphere)   window.nexonSphere.setState('idle');
        if (window.nexonAvatar)   window.nexonAvatar.stopTalking();
        return;
      }

      const sentence = sentences[idx++];
      if (!sentence.trim()) { speakNext(); return; }

      const utter     = new SpeechSynthesisUtterance(sentence);
      if (voice)        utter.voice  = voice;
      utter.lang      = language === 'hi' ? 'hi-IN' : 'en-US';
      utter.rate      = params.rate;
      utter.pitch     = params.pitch;
      utter.volume    = params.volume;

      utter.onend     = () => {
        // Small pause between sentences based on emotion
        if (params.pauseMs > 0) {
          setTimeout(speakNext, params.pauseMs);
        } else {
          speakNext();
        }
      };

      utter.onerror   = (e) => {
        if (e.error !== 'interrupted') console.warn('[TTS] Error:', e.error);
        speakNext();
      };

      // Fix Chrome bug where speech stops after ~15 seconds
      this._chromeFix();

      this.synth.speak(utter);
    };

    speakNext();
  }

  // Chrome has a bug where it stops speaking after ~15s
  _chromeFix() {
    const s = this.synth;
    if (!s.speaking) return;
    s.pause();
    s.resume();
  }

  stop() {
    this.synth?.cancel();
    this.isSpeaking = false;
    if (window.nexonWaveform) window.nexonWaveform.setMode('idle');
    if (window.nexonSphere)   window.nexonSphere.setState('idle');
    if (window.nexonAvatar)   window.nexonAvatar?.stopTalking();
  }

  setEmotion(emotion) { this.currentEmotion = emotion; }

  // ── Text cleaning ─────────────────────────────────────────

  _cleanText(text) {
    return text
      // Remove markdown formatting
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g,    '$1')
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`([^`]+)`/g,   '$1')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      // Remove context prefixes
      .replace(/\[Visual(?:\/Voice)? context:[^\]]*\]/g, '')
      .replace(/\[Voice analysis:[^\]]*\]/g, '')
      .replace(/\[Relevant memories[^\]]*\]/g, '')
      // Remove emojis for cleaner speech
      .replace(/[\u{1F300}-\u{1FFFF}]/gu, '')
      .replace(/[⚡✅❌⚠️🔮🧠👁🎭]/g, '')
      // Clean up whitespace
      .replace(/\n+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      // Limit length
      .substring(0, 600);
  }

  _splitIntoSentences(text) {
    // Split on sentence boundaries
    return text
      .split(/(?<=[.!?])\s+/)
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  // ── Wake word listener (Web Speech Recognition API) ───────
  // This runs continuously in the background listening for
  // "Hey NEXON", "Hi NEXON", etc. without recording full audio.

  startWakeWordListener(onWakeWord) {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      console.log('[TTS] Web Speech Recognition not available for wake word listening');
      return;
    }
    if (this._wakeListening) return;

    this._onWakeWord = onWakeWord;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._wakeRecognizer    = new SpeechRecognition();

    this._wakeRecognizer.continuous    = true;
    this._wakeRecognizer.interimResults= true;
    this._wakeRecognizer.lang          = 'en-US';
    this._wakeRecognizer.maxAlternatives = 3;

    const WAKE_PATTERNS = [
      'hey nexon', 'hi nexon', 'hello nexon', 'ok nexon', 'okay nexon',
      'oye nexon', 'nexon', 'hey nexen', 'hi nexen',  // Common mishearings
      'नमस्ते नेक्सन', 'हाय नेक्सन',
    ];

    this._wakeRecognizer.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript.toLowerCase().trim();

        for (const pattern of WAKE_PATTERNS) {
          if (transcript.includes(pattern)) {
            console.log('[TTS] Wake word detected:', transcript);
            this._onWakeWord && this._onWakeWord(transcript);
            return;
          }
        }
      }
    };

    this._wakeRecognizer.onend = () => {
      // Auto-restart unless we deliberately stopped
      if (this._wakeListening) {
        setTimeout(() => {
          try { this._wakeRecognizer.start(); } catch(_) {}
        }, 500);
      }
    };

    this._wakeRecognizer.onerror = (e) => {
      if (e.error === 'not-allowed') {
        console.warn('[TTS] Wake word listener: microphone permission denied');
        this._wakeListening = false;
      }
    };

    try {
      this._wakeRecognizer.start();
      this._wakeListening = true;
      console.log('[TTS] Wake word listener started ✓');
    } catch(e) {
      console.warn('[TTS] Wake word listener failed to start:', e);
    }
  }

  stopWakeWordListener() {
    this._wakeListening = false;
    try { this._wakeRecognizer?.stop(); } catch(_) {}
    this._wakeRecognizer = null;
  }

  getVoiceInfo() {
    return {
      available: this.voices.length,
      selected : this.preferredVoice?.name || 'None',
      lang     : this.preferredVoice?.lang || 'N/A',
    };
  }
}

// Global singleton
window.nexonTTS = new NexonTTSEngine();