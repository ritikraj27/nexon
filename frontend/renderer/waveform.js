// frontend/renderer/waveform.js — FIXED VERSION
// Fixes: canvas sizing on resize, proper cleanup

class WaveformVisualizer {
  constructor(canvasId, labelId) {
    this.canvas    = document.getElementById(canvasId);
    this.ctx       = this.canvas?.getContext('2d');
    this.labelEl   = document.getElementById(labelId);
    this.mode      = 'idle';
    this.animFrame = null;
    this.audioCtx  = null;
    this.analyser  = null;
    this.source    = null;
    this.simPhase  = 0;

    if (!this.canvas || !this.ctx) { console.warn('[Waveform] Canvas not found'); return; }
    this._resize();
    this._startAnimation();

    window.addEventListener('resize', () => this._resize());
  }

  connectMicStream(stream) {
    try {
      if (!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (this.source) { try { this.source.disconnect(); } catch(_) {} }
      this.analyser             = this.audioCtx.createAnalyser();
      this.analyser.fftSize     = 128;
      this.source               = this.audioCtx.createMediaStreamSource(stream);
      this.source.connect(this.analyser);
    } catch(e) { console.warn('[Waveform] Stream connect failed:', e); }
  }

  disconnectMic() {
    if (this.source) { try { this.source.disconnect(); } catch(_) {} this.source = null; }
  }

  setMode(mode) {
    this.mode = mode;
    const labels = { idle:'AMBIENT', user:'LISTENING', assistant:'SPEAKING' };
    if (this.labelEl) this.labelEl.textContent = labels[mode] || 'AMBIENT';
  }

  _startAnimation() {
    const draw = () => { this.animFrame = requestAnimationFrame(draw); this._draw(); };
    draw();
  }

  _draw() {
    if (!this.ctx || !this.canvas) return;
    const W   = this.canvas.width;
    const H   = this.canvas.height;
    const BAR = 48;
    const bW  = (W / BAR) * 0.6;
    const gap = (W / BAR) * 0.4;

    this.ctx.clearRect(0, 0, W, H);

    let freq = null;
    if (this.analyser && this.mode === 'user') {
      const data = new Uint8Array(this.analyser.frequencyBinCount);
      this.analyser.getByteFrequencyData(data);
      freq = data;
    }

    this.simPhase += this.mode === 'idle' ? 0.025 : 0.1;

    for (let i = 0; i < BAR; i++) {
      let bH;
      if (freq && this.mode === 'user') {
        const idx = Math.floor(i * freq.length / BAR);
        bH = (freq[idx] / 255) * H * 0.85;
      } else if (this.mode === 'assistant') {
        const dist = Math.abs(i - BAR/2) / (BAR/2);
        bH = (Math.sin(this.simPhase - dist * 4) * 0.5 + 0.5) * H * 0.65 * (1 - dist * 0.3);
      } else {
        bH = (Math.sin(this.simPhase * 0.4 + i * 0.35) * 0.5 + 0.5) * H * 0.10 + 2;
      }

      const x = i * (bW + gap) + gap / 2;
      const y = (H - bH) / 2;

      let color;
      if (this.mode === 'user') {
        const t = bH / (H * 0.85);
        color = `rgba(0, ${Math.floor(180 + 75*t)}, 255, ${0.5 + t*0.5})`;
      } else if (this.mode === 'assistant') {
        const t = bH / (H * 0.65);
        color = `rgba(${Math.floor(138 + 100*t)}, 43, ${Math.floor(226-160*t)}, ${0.5+t*0.5})`;
      } else {
        color = 'rgba(0, 212, 255, 0.15)';
      }

      this.ctx.fillStyle  = color;
      this.ctx.shadowBlur = this.mode !== 'idle' && bH > 6 ? 4 : 0;
      this.ctx.shadowColor= this.mode === 'user' ? '#00d4ff' : '#8a2be2';
      this.ctx.beginPath();
      if (this.ctx.roundRect) {
        this.ctx.roundRect(x, y, Math.max(bW, 1), Math.max(bH, 2), bW / 2);
      } else {
        this.ctx.rect(x, y, Math.max(bW, 1), Math.max(bH, 2));
      }
      this.ctx.fill();
      this.ctx.shadowBlur = 0;
    }
  }

  _resize() {
    if (!this.canvas) return;
    const container = this.canvas.parentElement;
    if (!container) return;
    this.canvas.width  = Math.max(200, container.clientWidth - 40);
    this.canvas.height = 54;
  }

  destroy() {
    if (this.animFrame) cancelAnimationFrame(this.animFrame);
    if (this.audioCtx?.state !== 'closed') this.audioCtx?.close();
  }
}

window.nexonWaveform = new WaveformVisualizer('waveform-canvas', 'waveform-label');