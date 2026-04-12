// frontend/renderer/avatar.js — FIXED VERSION
// Fix: Canvas properly sized, emotion updates work correctly

class EmotionAvatar {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) { console.warn('[Avatar] Canvas not found:', canvasId); return; }

    // Set explicit pixel size
    this.W = 120; this.H = 120;
    this.canvas.width  = this.W;
    this.canvas.height = this.H;
    this.ctx = this.canvas.getContext('2d');

    // Current animated state
    this.cur = { smile:0, eyeOpen:1, browRaise:0, mouthOpen:0, aura:0.2, hue:200 };
    this.tgt = { ...this.cur };

    this._isTalking = false;
    this._talkPhase = 0;
    this._isBlinking= false;
    this._particles = Array.from({ length:12 }, () => this._newParticle());
    this._animFrame = null;

    this._animate();
    this._schedBlink();
    console.log('[Avatar] Initialized ✓');
  }

  // ── Public API ───────────────────────────────────────────

  updateEmotion(emotionName, confidence = 0.8) {
    if (!emotionName) return;
    const w = Math.max(0.3, Math.min(1, confidence));
    const presets = {
      HAPPY    : { smile:0.8*w, eyeOpen:0.9, browRaise:0.2,    mouthOpen:0.15*w, aura:0.8, hue:140 },
      SAD      : { smile:-0.6*w,eyeOpen:0.6, browRaise:-0.3,   mouthOpen:0.08,   aura:0.3, hue:220 },
      ANGRY    : { smile:-0.5*w,eyeOpen:0.7, browRaise:-0.8,   mouthOpen:0.2,    aura:0.9, hue:0   },
      SURPRISED: { smile:0.1,   eyeOpen:1.4, browRaise:0.9,    mouthOpen:0.6*w,  aura:0.7, hue:50  },
      FEARFUL  : { smile:-0.2,  eyeOpen:1.2, browRaise:0.5,    mouthOpen:0.3,    aura:0.6, hue:200 },
      DISGUSTED: { smile:-0.4,  eyeOpen:0.75,browRaise:-0.5,   mouthOpen:0.1,    aura:0.4, hue:80  },
      NEUTRAL  : { smile:0,     eyeOpen:1.0, browRaise:0,      mouthOpen:0,      aura:0.2, hue:200 },
    };
    const p = presets[emotionName?.toUpperCase()] || presets.NEUTRAL;
    Object.assign(this.tgt, p);
  }

  startTalking() { this._isTalking = true; }
  stopTalking()  { this._isTalking = false; this.tgt.mouthOpen = 0; }
  blink()        { this._isBlinking = true; setTimeout(() => { this._isBlinking = false; }, 140); }

  // ── Animation ────────────────────────────────────────────

  _animate() {
    this._animFrame = requestAnimationFrame(() => this._animate());
    this._lerp();
    this._draw();
  }

  _lerp() {
    const S = 0.08;
    for (const k of Object.keys(this.cur)) {
      this.cur[k] += (this.tgt[k] - this.cur[k]) * S;
    }
    if (this._isTalking) {
      this._talkPhase += 0.3;
      this.cur.mouthOpen = 0.15 + Math.abs(Math.sin(this._talkPhase)) * 0.4;
    }
    if (this._isBlinking) this.cur.eyeOpen = 0;
    for (const p of this._particles) {
      p.angle  += p.speed;
      p.life   += 0.01;
      p.opacity = Math.sin(p.life * Math.PI) * this.cur.aura * 0.6;
      if (p.life >= 1) Object.assign(p, this._newParticle(), { life:0 });
    }
  }

  _draw() {
    const { ctx, W, H } = this;
    const cx = W/2, cy = H/2;
    ctx.clearRect(0, 0, W, H);
    const { smile, eyeOpen, browRaise, mouthOpen, aura, hue } = this.cur;

    // Aura glow
    if (aura > 0.05) {
      const g = ctx.createRadialGradient(cx, cy, 18, cx, cy, 52);
      g.addColorStop(0, `hsla(${hue},80%,60%,${aura*0.25})`);
      g.addColorStop(1, `hsla(${hue},80%,60%,0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, 52, 0, Math.PI*2); ctx.fill();
    }

    // Particles
    ctx.save();
    for (const p of this._particles) {
      if (p.opacity < 0.01) continue;
      const px = cx + Math.cos(p.angle)*p.r, py = cy + Math.sin(p.angle)*p.r*0.85;
      ctx.fillStyle = `hsla(${hue},80%,65%,${p.opacity})`;
      ctx.beginPath(); ctx.arc(px, py, p.sz, 0, Math.PI*2); ctx.fill();
    }
    ctx.restore();

    // Face oval
    const fg = ctx.createRadialGradient(cx-6,cy-6,4,cx,cy,34);
    fg.addColorStop(0, `hsla(${hue},40%,20%,0.96)`);
    fg.addColorStop(1, `hsla(${hue},60%,10%,0.96)`);
    ctx.fillStyle = fg; ctx.strokeStyle = `hsla(${hue},70%,55%,0.8)`; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.ellipse(cx, cy+2, 30, 34, 0, 0, Math.PI*2); ctx.fill(); ctx.stroke();

    // Eyes
    this._eye(cx-10, cy-5, hue, eyeOpen);
    this._eye(cx+10, cy-5, hue, eyeOpen);

    // Eyebrows
    const raise = browRaise * 4;
    ctx.strokeStyle = `hsla(${hue},60%,60%,0.9)`; ctx.lineWidth = 1.8; ctx.lineCap = 'round';
    const lf = browRaise < -0.3 ? 2 : 0, rf = browRaise < -0.3 ? 2 : 0;
    ctx.beginPath(); ctx.moveTo(cx-18,cy-12-raise+lf); ctx.quadraticCurveTo(cx-10,cy-15-raise,cx-3,cy-12-raise); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx+3, cy-12-raise); ctx.quadraticCurveTo(cx+10,cy-15-raise,cx+18,cy-12-raise+rf); ctx.stroke();

    // Nose dot
    ctx.fillStyle = `hsla(${hue},50%,45%,0.35)`;
    ctx.beginPath(); ctx.ellipse(cx,cy+4,2.2,3,0,0,Math.PI*2); ctx.fill();

    // Mouth
    const mW = 13, cY = smile*7;
    ctx.strokeStyle = `hsla(${hue},60%,55%,0.9)`; ctx.lineWidth=1.8; ctx.lineCap='round';
    if (mouthOpen > 0.12) {
      ctx.fillStyle='rgba(0,0,0,0.75)';
      ctx.beginPath(); ctx.moveTo(cx-mW,cy+16); ctx.quadraticCurveTo(cx,cy+16+cY+mouthOpen*8,cx+mW,cy+16);
      ctx.quadraticCurveTo(cx,cy+16+cY-mouthOpen*4,cx-mW,cy+16); ctx.closePath(); ctx.fill(); ctx.stroke();
      if (smile > 0.3 && mouthOpen > 0.18) {
        ctx.fillStyle='rgba(255,255,255,0.35)';
        ctx.beginPath(); ctx.ellipse(cx,cy+16+cY+2,mW*0.5,mouthOpen*2.5,0,0,Math.PI); ctx.fill();
      }
    } else {
      ctx.beginPath(); ctx.moveTo(cx-mW,cy+16); ctx.quadraticCurveTo(cx,cy+16+cY,cx+mW,cy+16); ctx.stroke();
    }

    // Scanlines
    ctx.fillStyle = 'rgba(0,0,0,0.05)';
    for (let y=0; y<H; y+=3) ctx.fillRect(0,y,W,1);
  }

  _eye(x, y, hue, open) {
    const o = Math.max(0, Math.min(1.5, open)), eH = 5*o;
    this.ctx.fillStyle=`hsla(${hue},30%,14%,0.9)`; this.ctx.strokeStyle=`hsla(${hue},60%,50%,0.7)`; this.ctx.lineWidth=1;
    this.ctx.beginPath(); this.ctx.ellipse(x,y,7,Math.max(0.5,eH),0,0,Math.PI*2); this.ctx.fill(); this.ctx.stroke();
    if (o > 0.1) {
      const ig = this.ctx.createRadialGradient(x-1,y-1,0.5,x,y,4);
      ig.addColorStop(0,`hsla(${hue},90%,70%,1)`); ig.addColorStop(0.6,`hsla(${hue},80%,45%,1)`); ig.addColorStop(1,`hsla(${hue},60%,20%,1)`);
      this.ctx.fillStyle=ig; this.ctx.beginPath(); this.ctx.arc(x,y,Math.min(4,eH*0.85),0,Math.PI*2); this.ctx.fill();
      this.ctx.fillStyle='rgba(0,0,0,0.9)'; this.ctx.beginPath(); this.ctx.arc(x,y,Math.min(2.2,eH*0.5),0,Math.PI*2); this.ctx.fill();
      this.ctx.fillStyle='rgba(255,255,255,0.85)'; this.ctx.beginPath(); this.ctx.arc(x-1.2,y-1.2,1.1,0,Math.PI*2); this.ctx.fill();
    }
  }

  _newParticle() {
    const a=Math.random()*Math.PI*2, r=36+Math.random()*14;
    return { angle:a, r, speed:(Math.random()-0.5)*0.018, sz:1+Math.random()*1.8, opacity:0, life:Math.random() };
  }

  _schedBlink() {
    const d = 2500 + Math.random()*3500;
    setTimeout(() => { this.blink(); this._schedBlink(); }, d);
  }

  destroy() {
    if (this._animFrame) cancelAnimationFrame(this._animFrame);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('avatar-canvas');
  if (canvas) window.nexonAvatar = new EmotionAvatar('avatar-canvas');
});
if ((document.readyState==='complete'||document.readyState==='interactive') && !window.nexonAvatar) {
  const canvas = document.getElementById('avatar-canvas');
  if (canvas) window.nexonAvatar = new EmotionAvatar('avatar-canvas');
}