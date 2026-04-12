// frontend/renderer/gaze.js
// ============================================================
// NEXON Gaze Tracking — Eye-Controlled Commands
// Uses MediaPipe FaceMesh iris landmarks to track where
// the user is looking on screen.
//
// Features:
//   - Real-time iris position tracking (left + right eye)
//   - Dwell detection: looking at element for N ms = trigger
//   - Gaze heatmap overlay (optional debug)
//   - Hands-free scrolling (look at top/bottom edge)
//   - Gaze-activated buttons (look + blink to click)
//
// Iris landmark indices (from FaceMesh refineLandmarks=true):
//   Left iris : 468, 469, 470, 471, 472
//   Right iris: 473, 474, 475, 476, 477
// ============================================================

class GazeTracker {
  /**
   * @param {Object} opts
   * @param {boolean} opts.enabled         - Start tracking immediately
   * @param {number}  opts.dwellMs         - Ms to dwell before trigger (default 1500)
   * @param {boolean} opts.showCursor      - Show gaze cursor overlay
   * @param {Function} opts.onGazeCommand  - Called with (command, element) on dwell
   */
  constructor(opts = {}) {
    this.enabled       = opts.enabled       ?? false;
    this.dwellMs       = opts.dwellMs       ?? 1500;
    this.showCursor    = opts.showCursor    ?? true;
    this.onGazeCommand = opts.onGazeCommand ?? (() => {});

    // Current gaze state
    this.gazeX         = 0;
    this.gazeY         = 0;
    this.smoothX       = 0;
    this.smoothY       = 0;
    this.isTracking    = false;
    this.blinkCount    = 0;

    // Dwell state
    this._dwellTarget  = null;
    this._dwellTimer   = null;
    this._dwellStart   = 0;

    // Smoothing
    this._SMOOTH_ALPHA = 0.15;  // Lower = smoother but more lag

    // Blink detection
    this._leftEarHistory  = [];
    this._rightEarHistory = [];
    this._BLINK_THRESHOLD = 0.2;
    this._lastBlinkTime   = 0;

    // Calibration offsets
    this._offsetX = 0;
    this._offsetY = 0;

    // Screen dimensions
    this._screenW = window.innerWidth;
    this._screenH = window.innerHeight;

    this._initCursor();
    this._initGazeZones();

    window.addEventListener('resize', () => {
      this._screenW = window.innerWidth;
      this._screenH = window.innerHeight;
    });

    console.log('[GazeTracker] Initialized. Enable via gazeTracker.enable()');
  }

  // ──────────────────────────────────────────
  // PUBLIC API
  // ──────────────────────────────────────────

  /** Enable gaze tracking. */
  enable() {
    this.enabled    = true;
    this.isTracking = true;
    if (this._cursor) this._cursor.style.display = 'block';
    this._showToast('👁️ Gaze tracking enabled — look at elements to interact');
    console.log('[GazeTracker] Enabled');
  }

  /** Disable gaze tracking. */
  disable() {
    this.enabled    = false;
    this.isTracking = false;
    this._clearDwell();
    if (this._cursor) this._cursor.style.display = 'none';
    console.log('[GazeTracker] Disabled');
  }

  /** Toggle enabled state. */
  toggle() {
    this.enabled ? this.disable() : this.enable();
  }

  /**
   * Process face mesh landmarks from MediaPipe.
   * Call this from camera.js _onFaceResults().
   *
   * @param {Array} landmarks - MediaPipe face mesh landmarks array
   * @param {number} canvasW  - Canvas width for coordinate mapping
   * @param {number} canvasH  - Canvas height for coordinate mapping
   */
  processFaceLandmarks(landmarks, canvasW, canvasH) {
    if (!this.enabled || !landmarks || landmarks.length < 478) return;

    // ── Iris centers ───────────────────────────────────────
    // Left iris: landmarks 468-472 (center = 468)
    // Right iris: landmarks 473-477 (center = 473)
    const leftIris  = landmarks[468];
    const rightIris = landmarks[473];

    if (!leftIris || !rightIris) return;

    // Average both irises for gaze estimate
    const rawGazeX = ((leftIris.x + rightIris.x) / 2);
    const rawGazeY = ((leftIris.y + rightIris.y) / 2);

    // Map normalized coords to screen coords
    // Note: video is mirrored so flip X
    const mappedX = (1 - rawGazeX) * this._screenW + this._offsetX;
    const mappedY = rawGazeY       * this._screenH * 0.85 + this._offsetY;

    // Smooth with EMA
    this.smoothX = this.smoothX * (1 - this._SMOOTH_ALPHA) + mappedX * this._SMOOTH_ALPHA;
    this.smoothY = this.smoothY * (1 - this._SMOOTH_ALPHA) + mappedY * this._SMOOTH_ALPHA;

    this.gazeX = Math.round(this.smoothX);
    this.gazeY = Math.round(this.smoothY);

    // ── Update gaze cursor ────────────────────────────────
    this._updateCursor(this.gazeX, this.gazeY);

    // ── Blink detection ───────────────────────────────────
    this._detectBlink(landmarks);

    // ── Dwell detection ───────────────────────────────────
    this._processDwell(this.gazeX, this.gazeY);

    // ── Edge scrolling ────────────────────────────────────
    this._processEdgeScroll(this.gazeX, this.gazeY);

    // ── Update debug info ─────────────────────────────────
    this._updateGazeDebug(this.gazeX, this.gazeY);
  }

  /**
   * Calibrate gaze offset using current face position.
   * User should look at screen center when calling this.
   */
  calibrate() {
    const centerX = this._screenW / 2;
    const centerY = this._screenH / 2;
    this._offsetX += centerX - this.gazeX;
    this._offsetY += centerY - this.gazeY;
    this._showToast('✅ Gaze calibrated to screen center');
  }

  // ──────────────────────────────────────────
  // CURSOR
  // ──────────────────────────────────────────

  _initCursor() {
    // Remove existing cursor
    const existing = document.getElementById('gaze-cursor');
    if (existing) existing.remove();

    this._cursor = document.createElement('div');
    this._cursor.id = 'gaze-cursor';
    this._cursor.style.cssText = `
      position: fixed;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 2px solid rgba(0, 212, 255, 0.8);
      background: rgba(0, 212, 255, 0.15);
      pointer-events: none;
      z-index: 99999;
      transform: translate(-50%, -50%);
      transition: width 0.1s, height 0.1s, background 0.1s;
      display: none;
      box-shadow: 0 0 12px rgba(0, 212, 255, 0.4);
    `;
    document.body.appendChild(this._cursor);

    // Dwell progress ring
    this._dwellRing = document.createElement('div');
    this._dwellRing.id = 'gaze-dwell-ring';
    this._dwellRing.style.cssText = `
      position: fixed;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      border: 3px solid transparent;
      border-top-color: var(--cyan, #00d4ff);
      pointer-events: none;
      z-index: 99998;
      transform: translate(-50%, -50%);
      display: none;
      animation: gaze-spin 1.5s linear infinite;
    `;
    document.body.appendChild(this._dwellRing);

    // Add spin animation
    if (!document.getElementById('gaze-styles')) {
      const style = document.createElement('style');
      style.id    = 'gaze-styles';
      style.textContent = `
        @keyframes gaze-spin {
          from { transform: translate(-50%, -50%) rotate(0deg); }
          to   { transform: translate(-50%, -50%) rotate(360deg); }
        }
        .gaze-highlight {
          outline: 2px solid rgba(0, 212, 255, 0.6) !important;
          box-shadow: 0 0 12px rgba(0, 212, 255, 0.3) !important;
        }
      `;
      document.head.appendChild(style);
    }
  }

  _updateCursor(x, y) {
    if (!this._cursor || !this.showCursor) return;
    this._cursor.style.left = `${x}px`;
    this._cursor.style.top  = `${y}px`;
    if (this._dwellRing) {
      this._dwellRing.style.left = `${x}px`;
      this._dwellRing.style.top  = `${y}px`;
    }
  }

  // ──────────────────────────────────────────
  // DWELL DETECTION
  // ──────────────────────────────────────────

  _initGazeZones() {
    // Gaze-aware elements are marked with data-gaze-action attribute
    // Example: <button data-gaze-action="send">Send</button>
    // Or: <div data-gaze-action="scroll-down">...</div>
  }

  _processDwell(x, y) {
    // Find element under gaze point
    const el = this._getGazableElement(x, y);

    if (!el) {
      this._clearDwell();
      return;
    }

    if (el === this._dwellTarget) {
      // Same target — check if dwell time exceeded
      const elapsed = Date.now() - this._dwellStart;
      const progress = Math.min(1, elapsed / this.dwellMs);

      // Update dwell ring opacity/color
      if (this._dwellRing) {
        this._dwellRing.style.display = 'block';
        this._dwellRing.style.borderTopColor =
          `rgba(0, 212, 255, ${0.4 + progress * 0.6})`;
      }

      if (elapsed >= this.dwellMs) {
        this._triggerDwell(el);
      }
    } else {
      // New target
      this._clearDwell();
      this._dwellTarget = el;
      this._dwellStart  = Date.now();
      el.classList.add('gaze-highlight');

      if (this._dwellRing) this._dwellRing.style.display = 'block';
    }
  }

  _getGazableElement(x, y) {
    // Get element at gaze point
    const el = document.elementFromPoint(x, y);
    if (!el) return null;

    // Walk up DOM tree to find gaze-aware element
    let target = el;
    for (let i = 0; i < 5; i++) {
      if (!target) break;
      if (
        target.dataset?.gazeAction ||
        target.tagName === 'BUTTON' ||
        target.classList.contains('gaze-target') ||
        target.classList.contains('history-item')
      ) {
        return target;
      }
      target = target.parentElement;
    }
    return null;
  }

  _triggerDwell(el) {
    const action = el.dataset?.gazeAction || el.tagName.toLowerCase();

    // Visual feedback
    el.classList.remove('gaze-highlight');
    el.style.transition = 'transform 0.1s';
    el.style.transform  = 'scale(0.97)';
    setTimeout(() => { el.style.transform = ''; }, 150);

    // Trigger click or custom action
    if (el.tagName === 'BUTTON' || el.tagName === 'INPUT') {
      el.click();
    }

    this.onGazeCommand(action, el);
    this._clearDwell();

    // Cooldown before next dwell
    this.enabled = false;
    setTimeout(() => { this.enabled = true; }, 800);
  }

  _clearDwell() {
    if (this._dwellTarget) {
      this._dwellTarget.classList.remove('gaze-highlight');
      this._dwellTarget = null;
    }
    if (this._dwellRing) this._dwellRing.style.display = 'none';
    this._dwellStart = 0;
  }

  // ──────────────────────────────────────────
  // BLINK DETECTION
  // ──────────────────────────────────────────

  _detectBlink(landmarks) {
    // Eye aspect ratio (EAR) for blink detection
    // Left eye: 159=top, 145=bottom, 33=left-corner, 133=right-corner
    // Right eye: 386=top, 374=bottom, 362=left-corner, 263=right-corner
    try {
      const leftEAR  = this._calcEAR(landmarks, 159, 145, 33, 133);
      const rightEAR = this._calcEAR(landmarks, 386, 374, 362, 263);
      const avgEAR   = (leftEAR + rightEAR) / 2;

      this._leftEarHistory.push(avgEAR);
      if (this._leftEarHistory.length > 10) this._leftEarHistory.shift();

      const recentAvg = this._leftEarHistory.slice(-5).reduce((a, b) => a + b, 0) / 5;
      const oldAvg    = this._leftEarHistory.slice(0, 5).reduce((a, b) => a + b, 0) / 5;

      // Blink = sudden drop in EAR
      const now = Date.now();
      if (oldAvg - recentAvg > this._BLINK_THRESHOLD && now - this._lastBlinkTime > 500) {
        this._lastBlinkTime = now;
        this.blinkCount++;
        this._onBlink();
      }
    } catch (e) { /* Ignore landmark errors */ }
  }

  _calcEAR(landmarks, topIdx, botIdx, leftIdx, rightIdx) {
    const top   = landmarks[topIdx];
    const bot   = landmarks[botIdx];
    const left  = landmarks[leftIdx];
    const right = landmarks[rightIdx];
    if (!top || !bot || !left || !right) return 0.3;

    const vertical   = Math.abs(top.y - bot.y);
    const horizontal = Math.abs(left.x - right.x) || 0.01;
    return vertical / horizontal;
  }

  _onBlink() {
    // Double blink = confirm dwell action
    if (this._dwellTarget) {
      this._triggerDwell(this._dwellTarget);
    }
    // Flash cursor
    if (this._cursor) {
      this._cursor.style.background = 'rgba(0, 212, 255, 0.8)';
      setTimeout(() => {
        if (this._cursor) this._cursor.style.background = 'rgba(0, 212, 255, 0.15)';
      }, 150);
    }
  }

  // ──────────────────────────────────────────
  // EDGE SCROLLING
  // ──────────────────────────────────────────

  _processEdgeScroll(x, y) {
    const EDGE_SIZE = 60;  // px from edge
    const SPEED     = 8;

    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const chatRect = chatMessages.getBoundingClientRect();
    if (x < chatRect.left || x > chatRect.right) return;

    if (y < chatRect.top + EDGE_SIZE) {
      // Look at top edge → scroll up
      chatMessages.scrollTop -= SPEED;
    } else if (y > chatRect.bottom - EDGE_SIZE) {
      // Look at bottom edge → scroll down
      chatMessages.scrollTop += SPEED;
    }
  }

  // ──────────────────────────────────────────
  // DEBUG + UTILS
  // ──────────────────────────────────────────

  _updateGazeDebug(x, y) {
    const el = document.getElementById('gaze-debug');
    if (el) {
      el.textContent = `👁 ${x},${y}`;
    }
  }

  _showToast(msg) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast     = document.createElement('div');
    toast.className = 'toast info';
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  /** Get current gaze position for external use. */
  getGazePosition() {
    return { x: this.gazeX, y: this.gazeY, tracking: this.isTracking };
  }
}

// Global singleton
window.gazeTracker = new GazeTracker({
  enabled    : false,
  dwellMs    : 1500,
  showCursor : true,
  onGazeCommand: (action, el) => {
    console.log('[GazeTracker] Dwell triggered:', action, el);
    // Show toast
    const container = document.getElementById('toast-container');
    if (container && action) {
      const t   = document.createElement('div');
      t.className = 'toast info';
      t.textContent = `👁️ Gaze: ${action}`;
      container.appendChild(t);
      setTimeout(() => t.remove(), 2000);
    }
  },
});