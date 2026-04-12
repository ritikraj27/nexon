// frontend/renderer/recorder.js — FINAL FIXED VERSION
// ============================================================
// ROOT CAUSE OF 500 ERROR:
// Electron's MediaRecorder produces audio/webm;codecs=opus blobs
// that are sometimes malformed (missing EBML header) when sent
// as raw bytes. Whisper's ffmpeg can't parse them.
//
// FIX: Use Web Audio API to capture PCM audio, then encode
// as proper WAV (44-byte header + 16-bit PCM samples).
// WAV is natively supported by Whisper with zero ffmpeg issues.
// ============================================================

class VoiceRecorder {
  constructor({ onTranscript, onStateChange, onError, onWakeWord }) {
    this.onTranscript  = onTranscript  || (() => {});
    this.onStateChange = onStateChange || (() => {});
    this.onError       = onError       || (() => {});
    this.onWakeWord    = onWakeWord    || (() => {});

    this.state         = 'idle';
    this.stream        = null;
    this.audioCtx      = null;
    this.scriptProcessor = null;
    this.pcmChunks     = [];   // Raw PCM Float32 samples

    // VAD
    this.analyser      = null;
    this.silenceTimer  = null;
    this.SILENCE_THRESH= 4;      // RMS threshold (out of 255)
    this.SILENCE_DELAY = 1800;   // ms silence before auto-stop
    this.MIN_RECORD_MS = 500;    // Don't stop within first 500ms
    this.recordStart   = 0;

    this.SAMPLE_RATE   = 16000;  // Whisper works best at 16kHz
    this.currentLanguage = 'en';
  }

  setLanguage(lang) { this.currentLanguage = lang; }

  // ── Microphone ───────────────────────────────────────────

  async _getStream() {
    if (this.stream && this.stream.active) return this.stream;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation  : true,
        noiseSuppression  : true,
        autoGainControl   : true,
        sampleRate        : this.SAMPLE_RATE,
        channelCount      : 1,
      }
    });
    return this.stream;
  }

  // ── Start Recording ──────────────────────────────────────

  async start() {
    if (this.state !== 'idle') return;
    try {
      const stream = await this._getStream();

      // Connect waveform visualizer
      if (window.nexonWaveform) {
        window.nexonWaveform.connectMicStream(stream);
        window.nexonWaveform.setMode('user');
      }
      if (window.nexonSphere) window.nexonSphere.setState('user');

      // Create AudioContext at 16kHz for Whisper compatibility
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: this.SAMPLE_RATE
      });

      const source = this.audioCtx.createMediaStreamSource(stream);

      // ScriptProcessor captures raw PCM chunks
      // bufferSize 4096 = ~256ms at 16kHz
      this.scriptProcessor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.pcmChunks = [];

      this.scriptProcessor.onaudioprocess = (e) => {
        if (this.state !== 'recording') return;
        // Copy the Float32 PCM data
        const inputData = e.inputBuffer.getChannelData(0);
        this.pcmChunks.push(new Float32Array(inputData));
      };

      source.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.audioCtx.destination);

      // VAD using AnalyserNode
      this.analyser         = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);

      this.recordStart = Date.now();
      this._setState('recording');
      this._startVAD();

    } catch (err) {
      this.onError(`Microphone error: ${err.message}`);
      this._setState('idle');
    }
  }

  // ── Stop Recording ───────────────────────────────────────

  stop() {
    if (this.state !== 'recording') return;
    // Don't stop if we just started
    if (Date.now() - this.recordStart < this.MIN_RECORD_MS) return;
    this._clearSilenceTimer();
    this._finalize();
  }

  toggle() {
    if (this.state === 'idle')       this.start();
    else if (this.state === 'recording') this.stop();
  }

  // ── VAD ──────────────────────────────────────────────────

  _startVAD() {
    if (!this.analyser) return;
    const data = new Uint8Array(this.analyser.frequencyBinCount);

    const check = () => {
      if (this.state !== 'recording') return;
      this.analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;

      if (avg < this.SILENCE_THRESH) {
        if (!this.silenceTimer && Date.now() - this.recordStart > this.MIN_RECORD_MS) {
          this.silenceTimer = setTimeout(() => {
            if (this.state === 'recording') this.stop();
          }, this.SILENCE_DELAY);
        }
      } else {
        this._clearSilenceTimer();
      }
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  }

  _clearSilenceTimer() {
    if (this.silenceTimer) { clearTimeout(this.silenceTimer); this.silenceTimer = null; }
  }

  // ── Finalize: Build WAV and transcribe ───────────────────

  async _finalize() {
    this._setState('processing');

    // Disconnect audio processing
    if (this.scriptProcessor) {
      try { this.scriptProcessor.disconnect(); } catch(_) {}
    }
    if (window.nexonWaveform) window.nexonWaveform.setMode('idle');
    if (window.nexonSphere)   window.nexonSphere.setState('idle');

    if (this.pcmChunks.length === 0) {
      this.onError('No audio recorded. Please try again.');
      this._setState('idle');
      return;
    }

    // Merge all PCM chunks
    const totalSamples = this.pcmChunks.reduce((sum, c) => sum + c.length, 0);
    const merged       = new Float32Array(totalSamples);
    let offset         = 0;
    for (const chunk of this.pcmChunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    // Must have at least 0.3 seconds of audio
    const durationMs = (merged.length / this.SAMPLE_RATE) * 1000;
    if (durationMs < 300) {
      this.onError('Recording too short. Please speak for at least 0.5 seconds.');
      this._setState('idle');
      return;
    }

    // Convert Float32 PCM → 16-bit PCM WAV bytes
    const wavBuffer = this._float32ToWav(merged, this.SAMPLE_RATE);

    try {
      let result = null;

      if (window.nexonAPI?.transcribeAudio) {
        // Electron IPC — send as WAV
        result = await window.nexonAPI.transcribeAudio(
          wavBuffer,
          this.currentLanguage === 'hinglish' ? '' : this.currentLanguage,
          'wav'   // Tell backend it's WAV
        );
      } else {
        // Browser fallback
        const blob     = new Blob([wavBuffer], { type: 'audio/wav' });
        const formData = new FormData();
        formData.append('audio',    blob, 'recording.wav');
        formData.append('language', this.currentLanguage === 'hinglish' ? '' : this.currentLanguage);
        formData.append('format',   'wav');
        formData.append('analyze_stress', 'true');
        const resp = await fetch('http://127.0.0.1:8000/transcribe', { method:'POST', body:formData });
        result     = await resp.json();
      }

      const text       = result?.text?.trim();
      const stressData = result?.voice_stress || {};

      if (text) {
        const el = document.getElementById('stat-transcript');
        if (el) { el.textContent = text.substring(0,25)+(text.length>25?'…':''); el.title=text; }
        this.onTranscript(text, result?.language || this.currentLanguage, result?.is_wake_word || false, stressData);
      } else {
        this.onError('No speech detected. Please speak clearly and try again.');
      }

    } catch (err) {
      console.error('[Recorder] Transcription error:', err);
      this.onError(`Transcription failed: ${err.message}`);
    } finally {
      this._cleanup();
      this._setState('idle');
    }
  }

  // ── WAV Encoder ──────────────────────────────────────────

  /**
   * Convert Float32Array PCM samples to a proper WAV ArrayBuffer.
   * WAV format: RIFF header (44 bytes) + 16-bit PCM samples.
   * This is natively supported by Whisper/ffmpeg with zero issues.
   */
  _float32ToWav(samples, sampleRate) {
    const numChannels = 1;
    const bitsPerSample = 16;
    const byteRate     = sampleRate * numChannels * bitsPerSample / 8;
    const blockAlign   = numChannels * bitsPerSample / 8;
    const dataSize     = samples.length * 2;  // 2 bytes per 16-bit sample
    const bufferSize   = 44 + dataSize;

    const buffer = new ArrayBuffer(bufferSize);
    const view   = new DataView(buffer);

    // WAV header
    this._writeString(view, 0,  'RIFF');
    view.setUint32(4,  36 + dataSize,       true);  // Chunk size
    this._writeString(view, 8,  'WAVE');
    this._writeString(view, 12, 'fmt ');
    view.setUint32(16, 16,                  true);  // Subchunk1 size (PCM = 16)
    view.setUint16(20, 1,                   true);  // Audio format (PCM = 1)
    view.setUint16(22, numChannels,         true);
    view.setUint32(24, sampleRate,          true);
    view.setUint32(28, byteRate,            true);
    view.setUint16(32, blockAlign,          true);
    view.setUint16(34, bitsPerSample,       true);
    this._writeString(view, 36, 'data');
    view.setUint32(40, dataSize,            true);

    // Convert Float32 [-1, 1] → Int16 [-32768, 32767]
    let idx = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(idx, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      idx += 2;
    }

    return buffer;
  }

  _writeString(view, offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  // ── Cleanup ───────────────────────────────────────────────

  _cleanup() {
    this.pcmChunks = [];
    if (this.audioCtx?.state !== 'closed') {
      try { this.audioCtx.close(); } catch(_) {}
    }
    this.audioCtx       = null;
    this.scriptProcessor= null;
    this.analyser       = null;
  }

  _setState(s) { this.state = s; this.onStateChange(s); }

  destroy() {
    this._clearSilenceTimer();
    this._cleanup();
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
  }
}

window.NexonVoiceRecorder = VoiceRecorder;