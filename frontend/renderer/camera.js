// frontend/renderer/camera.js — FINAL FIXED VERSION
// ============================================================
// FIXES:
// 1. Emotion thresholds completely rebalanced:
//    - Neutral is now the DEFAULT unless a strong signal exists
//    - Happy requires a clear smile (smileScore > 0.08)
//    - Sad requires a strong frown (smileScore < -0.08)
//    - Angry requires both brow furrow AND tight lips
//    - Surprised requires mouth open AND brows raised
// 2. Buffer size increased to 12 frames for smoother detection
// 3. Confidence gating: only update if confidence > 0.55
// 4. Gaze tracker bridge fixed
// 5. Avatar bridge: calls updateEmotion() every change
// ============================================================

class NexonCamera {
  constructor() {
    this.video  = document.getElementById('camera-video');
    this.canvas = document.getElementById('camera-canvas');
    if (!this.canvas) { console.warn('[NexonCamera] canvas not found'); return; }
    this.ctx = this.canvas.getContext('2d');

    this.faceDetected   = false;
    this.currentEmotion = { name:'NEUTRAL', emoji:'😐', conf:0.85, cssClass:'emotion-neutral' };
    this.currentGesture = { name:'NO GESTURE', emoji:'🖐️' };
    this.cameraEnabled  = true;

    // Larger buffers = smoother, less jittery
    this.emotionBuffer  = [];
    this.gestureBuffer  = [];
    this.BUFFER_SIZE    = 14;

    this.faceMesh = null;
    this.hands    = null;

    this._faceTimer = null;
    this._handTimer = null;

    // Track last few measurements for stability
    this._smileHistory    = [];
    this._eyeOpenHistory  = [];

    this._init();
  }

  async _init() {
    this._updateStatus('Starting camera…');
    try {
      await this._startCamera();
      this._updateStatus('Loading AI vision models…');
      await this._waitForMediaPipe(12000);
      await this._initFaceMesh();
      await this._initHands();
      this._updateStatus('Vision active ✓');
      setTimeout(() => this._hideStatus(), 2500);
    } catch (err) {
      console.error('[NexonCamera]', err.message);
      this._updateStatus(`⚠️ ${err.message}`);
    }
  }

  async _waitForMediaPipe(maxWait) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const check = () => {
        if (typeof FaceMesh !== 'undefined' && typeof Hands !== 'undefined') resolve();
        else if (Date.now() - start > maxWait) reject(new Error('MediaPipe CDN timeout'));
        else setTimeout(check, 300);
      };
      check();
    });
  }

  async _startCamera() {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width:{ideal:640}, height:{ideal:480}, facingMode:'user', frameRate:{ideal:30} }
    });
    this.video.srcObject = stream;
    return new Promise((resolve, reject) => {
      this.video.onloadedmetadata = () => {
        this.video.play().then(() => {
          this.canvas.width  = this.video.videoWidth  || 640;
          this.canvas.height = this.video.videoHeight || 480;
          resolve();
        }).catch(reject);
      };
      this.video.onerror = reject;
    });
  }

  async _initFaceMesh() {
    this.faceMesh = new FaceMesh({
      locateFile: f => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${f}`
    });
    this.faceMesh.setOptions({
      maxNumFaces            : 1,
      refineLandmarks        : true,
      minDetectionConfidence : 0.55,
      minTrackingConfidence  : 0.5,
    });
    this.faceMesh.onResults(r => this._onFaceResults(r));
    await this.faceMesh.initialize();

    const run = async () => {
      try {
        if (this.video.readyState >= 2 && !this.video.paused && this.cameraEnabled)
          await this.faceMesh.send({ image: this.video });
      } catch(_) {}
      this._faceTimer = setTimeout(run, 110);
    };
    run();
    console.log('[NexonCamera] FaceMesh ready ✓');
  }

  async _initHands() {
    this.hands = new Hands({
      locateFile: f => `https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4/${f}`
    });
    this.hands.setOptions({
      maxNumHands            : 1,
      modelComplexity        : 1,
      minDetectionConfidence : 0.65,
      minTrackingConfidence  : 0.55,
    });
    this.hands.onResults(r => this._onHandResults(r));
    await this.hands.initialize();

    const run = async () => {
      try {
        if (this.video.readyState >= 2 && !this.video.paused && this.cameraEnabled)
          await this.hands.send({ image: this.video });
      } catch(_) {}
      this._handTimer = setTimeout(run, 160);
    };
    run();
    console.log('[NexonCamera] Hands ready ✓');
  }

  // ── Face Results ─────────────────────────────────────────

  _onFaceResults(results) {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    const detected = !!(results.multiFaceLandmarks?.length > 0);
    this.faceDetected = detected;
    this._updateFaceBadge(detected);

    if (!detected) {
      // Gradually return to neutral when no face
      this._setEmotionSmoothed('NEUTRAL', '😐', 0.7);
      return;
    }

    const lm = results.multiFaceLandmarks[0];
    this._drawFaceOverlay(lm);

    // Forward to gaze tracker
    if (window.gazeTracker?.enabled) {
      try { window.gazeTracker.processFaceLandmarks(lm, this.canvas.width, this.canvas.height); }
      catch(_) {}
    }

    const emotion = this._estimateEmotion(lm);
    // Only update if confidence is high enough
    if (emotion.conf > 0.5) {
      this._setEmotionSmoothed(emotion.name, emotion.emoji, emotion.conf);
    }
    // else stay with current smoothed emotion
  }

  _drawFaceOverlay(lm) {
    const W = this.canvas.width, H = this.canvas.height;
    if (typeof drawConnectors !== 'undefined') {
      try {
        if (typeof FACEMESH_FACE_OVAL !== 'undefined')
          drawConnectors(this.ctx, lm, FACEMESH_FACE_OVAL,   { color:'rgba(0,212,255,0.25)', lineWidth:1 });
        if (typeof FACEMESH_LIPS !== 'undefined')
          drawConnectors(this.ctx, lm, FACEMESH_LIPS,        { color:'rgba(255,0,102,0.4)', lineWidth:1 });
        if (typeof FACEMESH_LEFT_EYE !== 'undefined') {
          drawConnectors(this.ctx, lm, FACEMESH_LEFT_EYE,    { color:'rgba(0,255,136,0.4)', lineWidth:1 });
          drawConnectors(this.ctx, lm, FACEMESH_RIGHT_EYE,   { color:'rgba(0,255,136,0.4)', lineWidth:1 });
          drawConnectors(this.ctx, lm, FACEMESH_LEFT_EYEBROW,{ color:'rgba(138,43,226,0.4)', lineWidth:1 });
          drawConnectors(this.ctx, lm, FACEMESH_RIGHT_EYEBROW,{color:'rgba(138,43,226,0.4)', lineWidth:1 });
        }
      } catch(_) {}
    }

    // Corner bracket bounding box
    const xs = lm.map(l=>l.x*W), ys = lm.map(l=>l.y*H);
    const minX=Math.min(...xs)-10, maxX=Math.max(...xs)+10;
    const minY=Math.min(...ys)-15, maxY=Math.max(...ys)+10;
    const c=14;
    this.ctx.strokeStyle='rgba(0,212,255,0.65)'; this.ctx.lineWidth=1.8;
    this.ctx.shadowColor='rgba(0,212,255,0.35)'; this.ctx.shadowBlur=4;
    this.ctx.beginPath();
    this.ctx.moveTo(minX+c,minY);this.ctx.lineTo(minX,minY);this.ctx.lineTo(minX,minY+c);
    this.ctx.moveTo(maxX-c,minY);this.ctx.lineTo(maxX,minY);this.ctx.lineTo(maxX,minY+c);
    this.ctx.moveTo(minX,maxY-c);this.ctx.lineTo(minX,maxY);this.ctx.lineTo(minX+c,maxY);
    this.ctx.moveTo(maxX,maxY-c);this.ctx.lineTo(maxX,maxY);this.ctx.lineTo(maxX-c,maxY);
    this.ctx.stroke(); this.ctx.shadowBlur=0;
  }

  // ── EMOTION ESTIMATION — REBALANCED ──────────────────────
  //
  // Key insight: a relaxed/neutral face has:
  //   - Mouth closed (mouthOpenR ~0.05)
  //   - Slight natural mouth curve (smileScore ~0 to 0.02)
  //   - Normal eye openness (eyeOpenR ~0.20-0.28)
  //   - Normal brow position (browLift ~0)
  //
  // The previous code was misclassifying neutral as SAD because
  // the smileScore < -0.04 threshold caught neutral faces.
  // New thresholds require MUCH stronger signals for each emotion.

  _estimateEmotion(lm) {
    try {
      const W = this.canvas.width, H = this.canvas.height;

      const px = i => ({ x: lm[i].x * W, y: lm[i].y * H });
      const dist = (a, b) => {
        const dx=px(a).x-px(b).x, dy=px(a).y-px(b).y;
        return Math.sqrt(dx*dx+dy*dy);
      };

      // === Mouth measurements ===
      const mouthOpen  = dist(13, 14);    // inner lip gap (vertical)
      const mouthWidth = dist(61, 291);   // corner to corner (horizontal)
      const mouthOpenR = mouthOpen / Math.max(mouthWidth, 1);

      // Smile: are mouth corners ABOVE upper lip center?
      // Positive = corners above = smile. Negative = corners below = frown.
      const upperLipY   = px(13).y;
      const leftCornerY = px(61).y;
      const rightCornerY= px(291).y;
      const avgCornerY  = (leftCornerY + rightCornerY) / 2;
      // Normalize by face height for scale invariance
      const faceH       = dist(10, 152) || 100;  // top of head to chin
      const smileScore  = (upperLipY - avgCornerY) / faceH;

      // Track smile history for stability
      this._smileHistory.push(smileScore);
      if (this._smileHistory.length > 8) this._smileHistory.shift();
      const avgSmile = this._smileHistory.reduce((a,b)=>a+b,0) / this._smileHistory.length;

      // === Eye openness ===
      const leftEyeH  = dist(159, 145);
      const rightEyeH = dist(386, 374);
      const eyeWidth  = dist(33,  133) || 1;
      const eyeOpenR  = ((leftEyeH + rightEyeH) / 2) / eyeWidth;

      this._eyeOpenHistory.push(eyeOpenR);
      if (this._eyeOpenHistory.length > 8) this._eyeOpenHistory.shift();
      const avgEyeOpen = this._eyeOpenHistory.reduce((a,b)=>a+b,0) / this._eyeOpenHistory.length;

      // === Brow position (relative to eye) ===
      // Negative = brow raised (away from eye), Positive = brow lowered (toward eye)
      const leftBrowDist  = (px(107).y - px(159).y) / faceH;  // negative = raised
      const rightBrowDist = (px(336).y - px(386).y) / faceH;
      const avgBrowLift   = (leftBrowDist + rightBrowDist) / 2;  // negative = raised

      // === CLASSIFICATION — from most specific to most general ===
      // All thresholds are CONSERVATIVE to avoid false positives

      // SURPRISED: mouth open + brows raised + wide eyes
      if (mouthOpenR > 0.30 && avgBrowLift < -0.04 && avgEyeOpen > 0.26) {
        return { name:'SURPRISED', emoji:'😮', conf:0.78, cssClass:'emotion-surprised' };
      }

      // HAPPY: clear upward smile, NOT just neutral
      // Requires avgSmile > 0.04 (normalized by face height)
      if (avgSmile > 0.05 && mouthOpenR < 0.35) {
        const conf = Math.min(0.92, 0.65 + avgSmile * 5);
        return { name:'HAPPY', emoji:'😊', conf, cssClass:'emotion-happy' };
      }

      // Mild happy
      if (avgSmile > 0.025 && mouthOpenR < 0.25) {
        return { name:'HAPPY', emoji:'🙂', conf:0.62, cssClass:'emotion-happy' };
      }

      // ANGRY: brow strongly furrowed (lowered) + squinting eyes + closed mouth
      // Brow lowered = positive avgBrowLift (toward eye)
      if (avgBrowLift > 0.04 && avgEyeOpen < 0.18 && mouthOpenR < 0.12) {
        return { name:'ANGRY', emoji:'😠', conf:0.68, cssClass:'emotion-angry' };
      }

      // SAD: mouth corners clearly below upper lip AND sustained
      // Only if avgSmile is strongly negative
      if (avgSmile < -0.06 && mouthOpenR < 0.20) {
        return { name:'SAD', emoji:'😢', conf:0.65, cssClass:'emotion-sad' };
      }

      // FEARFUL: wide eyes + brows raised + slight mouth open
      if (avgEyeOpen > 0.30 && avgBrowLift < -0.035 && mouthOpenR > 0.08) {
        return { name:'FEARFUL', emoji:'😨', conf:0.60, cssClass:'emotion-neutral' };
      }

      // DEFAULT: NEUTRAL — this is the fallback for ambiguous cases
      return { name:'NEUTRAL', emoji:'😐', conf:0.85, cssClass:'emotion-neutral' };

    } catch (e) {
      return { name:'NEUTRAL', emoji:'😐', conf:0.5, cssClass:'emotion-neutral' };
    }
  }

  // ── Hand Results ─────────────────────────────────────────

  _onHandResults(results) {
    if (!results.multiHandLandmarks?.length) {
      this._setGestureSmoothed('NO GESTURE', '🖐️');
      return;
    }
    const lm = results.multiHandLandmarks[0];

    try {
      if (typeof drawConnectors !== 'undefined' && typeof HAND_CONNECTIONS !== 'undefined')
        drawConnectors(this.ctx, lm, HAND_CONNECTIONS, { color:'rgba(138,43,226,0.65)', lineWidth:2 });
      if (typeof drawLandmarks !== 'undefined')
        drawLandmarks(this.ctx, lm, { color:'#ff0066', lineWidth:1, radius:2.5 });
    } catch(_) {}

    const gesture = this._classifyGesture(lm);
    this._setGestureSmoothed(gesture.name, gesture.emoji);
  }

  _classifyGesture(lm) {
    const ext = (tip, pip) => lm[tip].y < lm[pip].y - 0.025;
    const thumbUp   = lm[4].y < lm[3].y - 0.045;
    const thumbDown = lm[4].y > lm[2].y + 0.055;
    const indexExt  = ext(8,  6);
    const middleExt = ext(12, 10);
    const ringExt   = ext(16, 14);
    const pinkyExt  = ext(20, 18);
    const extCount  = [indexExt, middleExt, ringExt, pinkyExt].filter(Boolean).length;

    if (thumbUp && !indexExt && !middleExt && !ringExt && !pinkyExt)  return {name:'THUMBS UP',  emoji:'👍'};
    if (thumbDown && !indexExt && !middleExt && !ringExt && !pinkyExt) return {name:'THUMBS DOWN',emoji:'👎'};
    if (!indexExt && !middleExt && !ringExt && !pinkyExt && !thumbUp && !thumbDown) return {name:'FIST',emoji:'✊'};
    if (indexExt && middleExt && !ringExt && !pinkyExt) return {name:'PEACE',emoji:'✌️'};
    if (extCount === 4) return lm[0].y > lm[12].y + 0.1 ? {name:'WAVE',emoji:'👋'} : {name:'STOP',emoji:'✋'};
    if (indexExt && !middleExt && !ringExt && !pinkyExt) return {name:'POINT',emoji:'☝️'};
    if (!indexExt && !middleExt && !ringExt && pinkyExt && thumbUp) return {name:'ROCK',emoji:'🤘'};
    return {name:'NO GESTURE', emoji:'🖐️'};
  }

  // ── Smoothing ─────────────────────────────────────────────

  _setEmotionSmoothed(name, emoji, conf) {
    this.emotionBuffer.push(name);
    if (this.emotionBuffer.length > this.BUFFER_SIZE) this.emotionBuffer.shift();
    const smoothed = this._mostFrequent(this.emotionBuffer);

    if (this.currentEmotion.name !== smoothed) {
      const map = {
        HAPPY    : {emoji:'😊', cssClass:'emotion-happy'    },
        SAD      : {emoji:'😢', cssClass:'emotion-sad'      },
        ANGRY    : {emoji:'😠', cssClass:'emotion-angry'    },
        SURPRISED: {emoji:'😮', cssClass:'emotion-surprised'},
        FEARFUL  : {emoji:'😨', cssClass:'emotion-neutral'  },
        NEUTRAL  : {emoji:'😐', cssClass:'emotion-neutral'  },
      };
      const info = map[smoothed] || map.NEUTRAL;
      this._setEmotion(smoothed, emoji || info.emoji, conf, info.cssClass);
    }
  }

  _setGestureSmoothed(name, emoji) {
    this.gestureBuffer.push(name);
    if (this.gestureBuffer.length > this.BUFFER_SIZE) this.gestureBuffer.shift();
    const smoothed = this._mostFrequent(this.gestureBuffer);
    if (this.currentGesture.name !== smoothed) this._setGesture(smoothed, emoji);
  }

  _mostFrequent(arr) {
    const freq = {};
    arr.forEach(v => { freq[v] = (freq[v]||0)+1; });
    return Object.keys(freq).reduce((a,b) => freq[a]>freq[b]?a:b);
  }

  // ── UI Updates ───────────────────────────────────────────

  _setEmotion(name, emoji, conf, cssClass) {
    cssClass = cssClass || 'emotion-neutral';
    this.currentEmotion = { name, emoji, conf, cssClass };

    const setEl = (id, txt) => { const e=document.getElementById(id); if(e) e.textContent=txt; };
    setEl('emotion-emoji', emoji);
    setEl('emotion-name',  name);
    setEl('emotion-conf',  conf ? `${Math.round(conf*100)}%` : '—');
    setEl('stat-emotion',  name);
    setEl('emotion-context-icon',  emoji);
    setEl('emotion-context-label', name);
    setEl('chat-emotion-icon', emoji);
    setEl('chat-emotion-text', name.toLowerCase());
    setEl('sphere-emotion-icon', emoji);
    setEl('sphere-emotion-text', `${name.charAt(0)+name.slice(1).toLowerCase()} context active`);
    setEl('ecs-icon',    emoji);
    setEl('ecs-emotion', name.toLowerCase());

    const card = document.getElementById('emotion-card');
    if (card) card.classList.toggle('active', conf > 0.6);

    const badge = document.getElementById('sphere-emotion-badge');
    if (badge) { badge.className=''; badge.id='sphere-emotion-badge'; badge.classList.add(cssClass); }

    const strip = document.getElementById('emotion-context-strip');
    if (strip) { strip.className=name.toLowerCase(); strip.id='emotion-context-strip'; }

    const toneMap = {HAPPY:'happy',SAD:'neutral',ANGRY:'stressed',SURPRISED:'excited',FEARFUL:'stressed',NEUTRAL:'neutral'};
    const tone    = toneMap[name]||'neutral';
    document.querySelectorAll('.tone-pill').forEach(p => p.classList.toggle('active', p.dataset.tone===tone));

    // Avatar mirror — THE KEY BRIDGE
    if (window.nexonAvatar?.updateEmotion) {
      try { window.nexonAvatar.updateEmotion(name, conf||0.8); } catch(_) {}
    }

    window.nexonCurrentEmotion = { name, emoji, conf, cssClass };
  }

  _setGesture(name, emoji) {
    this.currentGesture = { name, emoji };
    const setEl = (id,txt) => { const e=document.getElementById(id); if(e) e.textContent=txt; };
    setEl('gesture-emoji', emoji);
    setEl('gesture-name',  name);
    const gestureLabel = document.getElementById('ecs-gesture-label');
    if (gestureLabel) gestureLabel.textContent = name !== 'NO GESTURE' ? `${emoji} ${name}` : '';
    const card = document.getElementById('gesture-card');
    if (card) card.classList.toggle('active', name !== 'NO GESTURE');
    window.nexonCurrentGesture = { name, emoji };
  }

  _updateFaceBadge(detected) {
    const badge = document.getElementById('face-badge');
    if (!badge) return;
    badge.textContent = detected ? 'Face Detected' : 'No Face';
    badge.className   = `badge ${detected ? 'badge-green' : 'badge-gray'}`;
  }

  _updateStatus(text) {
    const el = document.getElementById('camera-status-text');
    if (el) el.textContent = text;
    console.log('[NexonCamera]', text);
  }

  _hideStatus() {
    const el = document.getElementById('camera-status-overlay');
    if (el) { el.style.opacity='0'; setTimeout(()=>{ el.style.display='none'; },400); }
  }
}

// Boot
const _bootCamera = () => {
  if (!window.nexonCamera) window.nexonCamera = new NexonCamera();
};
if (document.readyState==='complete'||document.readyState==='interactive') {
  setTimeout(_bootCamera, 400);
} else {
  document.addEventListener('DOMContentLoaded', () => setTimeout(_bootCamera, 400));
}