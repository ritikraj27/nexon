// frontend/renderer/parallel.js
// ============================================================
// NEXON Parallel Task Dashboard
// Shows real-time progress of multiple concurrent agent tasks.
// Connects to /ws/parallel WebSocket for live status updates.
//
// Features:
//   - Live task cards with spinning progress indicators
//   - Per-task success/fail badges
//   - Overall completion bar
//   - Auto-hide after completion
//   - WebSocket reconnect on disconnect
// ============================================================

class ParallelDashboard {
  /**
   * @param {string} containerId - ID of container element to render dashboard into
   */
  constructor(containerId) {
    this.containerId = containerId;
    this.container   = document.getElementById(containerId);
    this.tasks       = new Map();   // task_id → task object
    this.ws          = null;
    this.isVisible   = false;

    this._createDOM();
  }

  // ──────────────────────────────────────────
  // DOM CREATION
  // ──────────────────────────────────────────

  _createDOM() {
    if (!this.container) return;

    this.container.innerHTML = `
      <div id="pd-header">
        <span id="pd-title">⚡ Parallel Execution</span>
        <span id="pd-count">0 tasks</span>
        <button id="pd-close" onclick="nexonParallel.hide()">✕</button>
      </div>
      <div id="pd-progress-bar-wrap">
        <div id="pd-progress-bar"></div>
      </div>
      <div id="pd-tasks"></div>
      <div id="pd-summary"></div>
    `;
  }

  // ──────────────────────────────────────────
  // WEBSOCKET
  // ──────────────────────────────────────────

  connectWebSocket() {
    const wsUrl = 'ws://127.0.0.1:8000/ws/parallel';
    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          this._handleEvent(data);
        } catch (err) {
          console.error('[ParallelDash] WS parse error:', err);
        }
      };

      this.ws.onclose = () => {
        // Auto-reconnect after 3 seconds
        setTimeout(() => this.connectWebSocket(), 3000);
      };

      this.ws.onerror = (e) => {
        console.warn('[ParallelDash] WS error — will retry');
      };
    } catch (e) {
      console.warn('[ParallelDash] WebSocket not available');
    }
  }

  /**
   * Submit a parallel task request via WebSocket.
   * @param {string} text       - User command text
   * @param {number} sessionId  - Session ID
   * @param {string} language   - Language code
   */
  submitTask(text, sessionId, language = 'en') {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[ParallelDash] WebSocket not connected');
      return false;
    }
    this.ws.send(JSON.stringify({ text, session_id: sessionId, language }));
    return true;
  }

  // ──────────────────────────────────────────
  // EVENT HANDLING
  // ──────────────────────────────────────────

  _handleEvent(data) {
    switch (data.event) {
      case 'tasks_created':
        this._onTasksCreated(data);
        break;
      case 'task_started':
        this._onTaskStarted(data);
        break;
      case 'task_done':
        this._onTaskDone(data);
        break;
      case 'all_done':
        this._onAllDone(data);
        break;
      case 'complete':
        this._onComplete(data);
        break;
    }
  }

  _onTasksCreated(data) {
    this.tasks.clear();
    this.show();

    const countEl = document.getElementById('pd-count');
    if (countEl) countEl.textContent = `${data.count} tasks`;

    data.tasks.forEach(task => {
      this.tasks.set(task.task_id, task);
      this._renderTask(task);
    });

    this._updateProgress();
  }

  _onTaskStarted(data) {
    const task = this.tasks.get(data.task_id);
    if (task) {
      task.status = 'running';
      this._updateTaskCard(data.task_id, 'running');
    }
  }

  _onTaskDone(data) {
    const task = data.task;
    if (!task) return;

    this.tasks.set(task.task_id, task);
    this._updateTaskCard(task.task_id, task.status, task);
    this._updateProgress();
  }

  _onAllDone(data) {
    const result = data.result;
    if (!result) return;

    const summaryEl = document.getElementById('pd-summary');
    if (summaryEl) {
      const successCount = result.success_count || 0;
      const failCount    = result.fail_count    || 0;
      const totalMs      = result.total_ms      || 0;

      summaryEl.innerHTML = `
        <div class="pd-summary-row">
          <span class="pd-summary-success">✅ ${successCount} succeeded</span>
          ${failCount > 0 ? `<span class="pd-summary-fail">❌ ${failCount} failed</span>` : ''}
          <span class="pd-summary-time">⏱ ${totalMs}ms</span>
        </div>
      `;
    }

    // Auto-hide after 5 seconds
    setTimeout(() => this.hide(), 5000);
  }

  _onComplete(data) {
    this._onAllDone(data);
  }

  // ──────────────────────────────────────────
  // DOM UPDATES
  // ──────────────────────────────────────────

  _renderTask(task) {
    const tasksEl = document.getElementById('pd-tasks');
    if (!tasksEl) return;

    const card = document.createElement('div');
    card.id          = `pd-task-${task.task_id}`;
    card.className   = 'pd-task-card pd-status-pending';
    card.innerHTML   = this._taskCardHTML(task);
    tasksEl.appendChild(card);
  }

  _taskCardHTML(task) {
    const intent  = (task.intent || '').replace(/_/g, ' ');
    const statusIcon = {
      pending  : '<span class="pd-spinner">◌</span>',
      running  : '<span class="pd-spinner spinning">◌</span>',
      success  : '✅',
      failed   : '❌',
      cancelled: '⚪',
    }[task.status] || '◌';

    const msg = task.result?.message?.substring(0, 60) || '';

    return `
      <div class="pd-task-left">
        <span class="pd-task-icon">${statusIcon}</span>
        <div class="pd-task-info">
          <span class="pd-task-name">${intent}</span>
          ${msg ? `<span class="pd-task-msg">${msg}</span>` : ''}
        </div>
      </div>
      <div class="pd-task-right">
        ${task.duration_ms ? `<span class="pd-task-time">${task.duration_ms}ms</span>` : ''}
      </div>
    `;
  }

  _updateTaskCard(taskId, status, taskData = null) {
    const card = document.getElementById(`pd-task-${taskId}`);
    if (!card) return;

    // Update class
    card.className = `pd-task-card pd-status-${status}`;

    if (taskData) {
      card.innerHTML = this._taskCardHTML(taskData);
    }
  }

  _updateProgress() {
    const total    = this.tasks.size;
    const done     = [...this.tasks.values()].filter(t => t.status === 'success' || t.status === 'failed').length;
    const pct      = total > 0 ? (done / total) * 100 : 0;

    const bar = document.getElementById('pd-progress-bar');
    if (bar) {
      bar.style.width = `${pct}%`;
      if (pct >= 100) {
        bar.style.background = 'var(--green, #00ff88)';
      }
    }
  }

  // ──────────────────────────────────────────
  // VISIBILITY
  // ──────────────────────────────────────────

  show() {
    if (!this.container) return;
    this.isVisible = true;
    this.container.style.display = 'flex';
    this.container.classList.add('pd-visible');

    // Clear previous tasks
    const tasksEl   = document.getElementById('pd-tasks');
    const summaryEl = document.getElementById('pd-summary');
    if (tasksEl)   tasksEl.innerHTML   = '';
    if (summaryEl) summaryEl.innerHTML = '';
  }

  hide() {
    if (!this.container) return;
    this.isVisible = false;
    this.container.classList.remove('pd-visible');
    this.container.classList.add('pd-hiding');
    setTimeout(() => {
      this.container.style.display = 'none';
      this.container.classList.remove('pd-hiding');
    }, 300);
  }

  /**
   * Manually display results from a REST API parallel response
   * (when WebSocket not used).
   * @param {Object} parallelResult - Result from /chat parallel_tasks
   */
  displayRestResult(parallelResult) {
    if (!parallelResult?.tasks?.length) return;

    this.tasks.clear();
    this.show();

    const countEl = document.getElementById('pd-count');
    if (countEl) countEl.textContent = `${parallelResult.tasks.length} tasks`;

    parallelResult.tasks.forEach(task => {
      this.tasks.set(task.task_id, task);
      this._renderTask(task);
    });

    this._updateProgress();

    setTimeout(() => {
      this._onAllDone({ result: parallelResult });
    }, 500);
  }
}

// Singleton
window.nexonParallel = null;
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('parallel-dashboard');
  if (container) {
    window.nexonParallel = new ParallelDashboard('parallel-dashboard');
    window.nexonParallel.connectWebSocket();
  }
});