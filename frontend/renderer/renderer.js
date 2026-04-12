// frontend/renderer/renderer.js — FIXED VERSION
// ============================================================
// Fixes:
// 1. Dark/Light mode toggle with persistence
// 2. [Visual/Voice context: ...] prefix hidden from user messages
// 3. Sends original_text separately so DB stores clean version
// 4. Face enrollment page location added
// ============================================================

const state = {
  sessions      : [],
  activeSession : null,
  language      : 'en',
  mode          : 'text',
  commandCount  : 0,
  recorder      : null,
  userId        : 'default',
  voiceStress   : 0,
  memoryCount   : 0,
  isDarkMode    : true,   // Default dark
};

const $ = id => document.getElementById(id);
const DOM = {
  chatMessages   : $('chat-messages'),
  chatInput      : $('chat-input'),
  sendBtn        : $('send-btn'),
  historyList    : $('history-list'),
  micBtn         : $('mic-btn'),
  micLabel       : $('mic-label'),
  micIcon        : $('mic-icon'),
  statusDot      : $('status-dot'),
  statusText     : $('status-text'),
  modelName      : $('model-name'),
  statModel      : $('stat-model'),
  statCommands   : $('stat-commands'),
  statMemory     : $('stat-memory'),
  statStress     : $('stat-stress'),
  loadingOverlay : $('loading-overlay'),
  newChatLeft    : $('new-chat-btn-left'),
  newChatRight   : $('new-chat-btn-right'),
  attachBtn      : $('attach-btn'),
  mainGrid       : $('main-grid'),
  suggestionsList: $('suggestions-list'),
  memoryPillCount: $('memory-pill-count'),
  userName       : $('user-name'),
  userAvatar     : $('user-avatar'),
};

// ════════════════════════════════════════════════════════════
// DARK / LIGHT MODE
// ════════════════════════════════════════════════════════════

function initTheme() {
  const saved = localStorage.getItem('nexon-theme') || 'dark';
  state.isDarkMode = saved === 'dark';
  applyTheme(state.isDarkMode);
}

function applyTheme(isDark) {
  const root = document.documentElement;
  if (isDark) {
    root.style.setProperty('--bg-deep',       '#0a0e1a');
    root.style.setProperty('--bg-panel',      '#131829');
    root.style.setProperty('--bg-card',       '#1a2040');
    root.style.setProperty('--bg-input',      '#0d1224');
    root.style.setProperty('--text-primary',  '#e8eaf6');
    root.style.setProperty('--text-secondary','#7986cb');
    root.style.setProperty('--text-muted',    '#3d4a7a');
    root.style.setProperty('--border',        'rgba(0, 212, 255, 0.12)');
    root.style.setProperty('--border-bright', 'rgba(0, 212, 255, 0.35)');
    document.body.classList.remove('light-mode');
    document.body.classList.add('dark-mode');
    const btn = $('theme-toggle-btn');
    if (btn) { btn.textContent = '☀️'; btn.title = 'Switch to Light Mode'; }
  } else {
    root.style.setProperty('--bg-deep',       '#f0f4f8');
    root.style.setProperty('--bg-panel',      '#ffffff');
    root.style.setProperty('--bg-card',       '#f8fafc');
    root.style.setProperty('--bg-input',      '#eef2f7');
    root.style.setProperty('--text-primary',  '#1a1f36');
    root.style.setProperty('--text-secondary','#4a5568');
    root.style.setProperty('--text-muted',    '#a0aec0');
    root.style.setProperty('--border',        'rgba(0, 100, 200, 0.15)');
    root.style.setProperty('--border-bright', 'rgba(0, 100, 200, 0.3)');
    document.body.classList.remove('dark-mode');
    document.body.classList.add('light-mode');
    const btn = $('theme-toggle-btn');
    if (btn) { btn.textContent = '🌙'; btn.title = 'Switch to Dark Mode'; }
  }
}

function toggleTheme() {
  state.isDarkMode = !state.isDarkMode;
  applyTheme(state.isDarkMode);
  localStorage.setItem('nexon-theme', state.isDarkMode ? 'dark' : 'light');
  showToast(`Switched to ${state.isDarkMode ? 'Dark' : 'Light'} Mode`, 'info', 1500);
}

// Expose globally for HTML onclick
window.toggleTheme = toggleTheme;

// ════════════════════════════════════════════════════════════
// RESIZABLE PANELS
// ════════════════════════════════════════════════════════════

function initResizablePanels() {
  const grid      = DOM.mainGrid;
  const leftPanel = $('left-panel');
  const rightPanel= $('right-panel');
  const handleL   = $('handle-left');
  const handleR   = $('handle-right');
  if (!grid || !handleL || !handleR) return;

  const setLW = w => {
    w = Math.max(180, Math.min(window.innerWidth * 0.38, w));
    if (leftPanel) leftPanel.style.width = `${w}px`;
    grid.style.setProperty('--left-w', `${w}px`);
  };
  const setRW = w => {
    w = Math.max(280, Math.min(window.innerWidth * 0.48, w));
    if (rightPanel) rightPanel.style.width = `${w}px`;
    grid.style.setProperty('--right-w', `${w}px`);
  };

  setLW(parseInt(localStorage.getItem('nexon-left-w')  || '280'));
  setRW(parseInt(localStorage.getItem('nexon-right-w') || '380'));

  let drag = null;
  const onDown = (e, dir) => {
    e.preventDefault();
    $(`handle-${dir}`)?.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    drag = { dir, startX: e.clientX, startL: leftPanel?.offsetWidth||280, startR: rightPanel?.offsetWidth||380 };
  };
  const onMove = e => {
    if (!drag) return;
    const dx = e.clientX - drag.startX;
    if (drag.dir === 'left') setLW(drag.startL + dx);
    else                     setRW(drag.startR - dx);
    window.nexonSphere?._onResize();
    window.nexonWaveform?._resize();
  };
  const onUp = () => {
    if (!drag) return;
    ['left','right'].forEach(d => $(`handle-${d}`)?.classList.remove('dragging'));
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    localStorage.setItem('nexon-left-w',  leftPanel?.offsetWidth?.toString());
    localStorage.setItem('nexon-right-w', rightPanel?.offsetWidth?.toString());
    drag = null;
  };

  handleL.addEventListener('mousedown', e => onDown(e, 'left'));
  handleR.addEventListener('mousedown', e => onDown(e, 'right'));
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
  handleL.addEventListener('dblclick', () => { setLW(280); localStorage.setItem('nexon-left-w','280'); });
  handleR.addEventListener('dblclick', () => { setRW(380); localStorage.setItem('nexon-right-w','380'); });
}

// ════════════════════════════════════════════════════════════
// EMOTION CONTEXT
// ════════════════════════════════════════════════════════════

function getCurrentEmotionContext() {
  const emotion = window.nexonCurrentEmotion || { name:'NEUTRAL', emoji:'😐', conf:0 };
  const gesture = window.nexonCurrentGesture || { name:'NO GESTURE', emoji:'🖐️' };
  const cam     = window.nexonCamera;
  const faceSeen= cam ? cam.faceDetected : false;
  const parts   = [];
  if (faceSeen && emotion.name !== 'NEUTRAL') {
    const pct = emotion.conf ? `${Math.round(emotion.conf * 100)}%` : '';
    parts.push(`facial expression: ${emotion.name}${pct ? ` (${pct})` : ''}`);
  } else if (faceSeen) {
    parts.push('neutral expression');
  }
  if (gesture.name !== 'NO GESTURE') parts.push(`gesture: ${gesture.name}`);
  if (state.voiceStress > 50)        parts.push(`voice stress: ${state.voiceStress}%`);
  return {
    emotion     : emotion.name, emoji: emotion.emoji, conf: emotion.conf,
    gesture     : gesture.name, gestureEmoji: gesture.emoji, faceSeen,
    voiceStress : state.voiceStress,
    contextString: parts.join(', '),
  };
}

/**
 * Build enriched text for LLM — keeps original text separate for DB storage.
 * Returns { enrichedText, originalText }
 */
function buildEnrichedPrompt(userText, ctx) {
  const parts = [];
  if (ctx.contextString) parts.push(`[Visual/Voice context: ${ctx.contextString}]`);
  const enriched = parts.length > 0 ? `${parts.join('\n')}\n\n${userText}` : userText;
  return { enrichedText: enriched, originalText: userText };
}

// ════════════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════════════

async function initNexon() {
  initTheme();
  initResizablePanels();
  await checkBackendHealth();
  await loadSessions();
  await loadMemoryStats();
  await loadSuggestions();
  initRecorder();
  bindEvents();
  const savedLang = await safeGetPreference('language') || 'en';
  setLanguage(savedLang);
  const savedTheme = localStorage.getItem('nexon-theme') || 'dark';
  state.isDarkMode = savedTheme === 'dark';
  applyTheme(state.isDarkMode);

  setInterval(loadSuggestions, 60000);
  setInterval(loadMemoryStats, 30000);
  setInterval(() => {
    if (DOM.statMemory) DOM.statMemory.textContent = `${state.sessions.length}s / ${state.memoryCount}m`;
  }, 5000);

  setTimeout(() => DOM.loadingOverlay?.classList.add('hidden'), 800);
}

// ════════════════════════════════════════════════════════════
// HEALTH
// ════════════════════════════════════════════════════════════

async function checkBackendHealth() {
  try {
    const health = await window.nexonAPI.health();
    setConnectionStatus('connected');
    const model = health.llm?.model || 'ollama';
    if (DOM.modelName) DOM.modelName.textContent = model;
    if (DOM.statModel) DOM.statModel.textContent = model;
  } catch {
    setConnectionStatus('disconnected');
    showToast('Backend offline. Run: uvicorn backend.main:app --reload', 'error', 5000);
    setTimeout(checkBackendHealth, 5000);
  }
}

function setConnectionStatus(s) {
  if (DOM.statusDot)  DOM.statusDot.className   = `status-dot ${s}`;
  if (DOM.statusText) DOM.statusText.textContent = {connected:'Connected',disconnected:'Disconnected',connecting:'Connecting…'}[s]||s;
}

// ════════════════════════════════════════════════════════════
// SESSIONS
// ════════════════════════════════════════════════════════════

async function loadSessions() {
  try {
    state.sessions = await window.nexonAPI.getSessions();
    const active   = state.sessions.find(s => s.is_active) || state.sessions[0];
    if (active) { state.activeSession = active; await loadChatHistory(active.id); }
    renderHistoryList();
  } catch(e) { console.error('[NEXON] sessions:', e); }
}

function renderHistoryList() {
  if (!DOM.historyList) return;
  DOM.historyList.innerHTML = '';
  if (!state.sessions.length) {
    DOM.historyList.innerHTML = '<div class="history-empty">No chats yet</div>';
    return;
  }
  state.sessions.forEach(s => {
    const item = document.createElement('div');
    item.className = `history-item${state.activeSession?.id === s.id ? ' active' : ''}`;
    const title = document.createElement('span');
    title.className   = 'history-item-title';
    // Clean any context prefix from title
    title.textContent = cleanDisplayText(s.title || `Chat ${s.id}`);
    const del = document.createElement('button');
    del.className   = 'history-delete-btn';
    del.textContent = '🗑️';
    del.addEventListener('click', e => { e.stopPropagation(); confirmDelete(s.id); });
    item.appendChild(title); item.appendChild(del);
    item.addEventListener('click', () => switchToSession(s.id));
    DOM.historyList.appendChild(item);
  });
}

/** Remove context prefixes from display text */
function cleanDisplayText(text) {
  if (!text) return '';
  return text
    .replace(/^\[Visual(?:\/Voice)? context:[^\]]*\]\n*/g, '')
    .replace(/^\[Voice analysis:[^\]]*\]\n*/g, '')
    .replace(/^\[Relevant memories[^\]]*\]\n*/g, '')
    .trim();
}

async function switchToSession(id) {
  if (state.activeSession?.id === id) return;
  try {
    await window.nexonAPI.switchSession(id);
    state.activeSession = state.sessions.find(s => s.id === id);
    await loadChatHistory(id);
    renderHistoryList();
  } catch { showToast('Failed to switch chat.','error'); }
}

async function createNewSession() {
  try {
    const s = await window.nexonAPI.createSession(state.language);
    state.sessions.unshift(s); state.activeSession = s;
    if (DOM.chatMessages) DOM.chatMessages.innerHTML = '';
    appendWelcomeMessage(); renderHistoryList();
    DOM.chatInput?.focus(); showToast('New chat started.','info');
  } catch { showToast('Failed to create chat.','error'); }
}

async function confirmDelete(id) {
  const s = state.sessions.find(x => x.id === id);
  if (!confirm(`Delete "${s?.title || `Chat ${id}`}"?`)) return;
  try {
    await window.nexonAPI.deleteSession(id);
    state.sessions = state.sessions.filter(x => x.id !== id);
    if (state.activeSession?.id === id) {
      state.activeSession = state.sessions[0] || null;
      if (DOM.chatMessages) DOM.chatMessages.innerHTML = '';
      if (state.activeSession) await loadChatHistory(state.activeSession.id);
      else await createNewSession();
    }
    renderHistoryList(); showToast('Deleted.','info');
  } catch { showToast('Delete failed.','error'); }
}

async function loadChatHistory(id) {
  try {
    const data = await window.nexonAPI.getHistory(id);
    if (DOM.chatMessages) DOM.chatMessages.innerHTML = '';
    if (!data.messages?.length) { appendWelcomeMessage(); return; }
    data.messages.forEach(m => {
      // Clean any context prefix from stored messages
      const cleanContent = cleanDisplayText(m.content);
      appendMessage(m.role, cleanContent, m.action_data, m.emotion, false);
    });
    scrollToBottom();
  } catch { appendWelcomeMessage(); }
}

// ════════════════════════════════════════════════════════════
// MEMORY
// ════════════════════════════════════════════════════════════

async function loadMemoryStats() {
  try {
    const resp = await fetch('http://127.0.0.1:8000/memory/stats');
    const data = await resp.json();
    state.memoryCount = data.total_nodes || 0;
    if (DOM.memoryPillCount) DOM.memoryPillCount.textContent = `${state.memoryCount} memories`;
  } catch { /* non-critical */ }
}

window.renderer_toggleMemoryPanel = async function() {
  const panel = $('memory-panel');
  if (!panel) return;
  const vis = panel.style.display !== 'none';
  if (vis) { panel.style.display = 'none'; return; }
  panel.style.display = 'flex';
  await renderer_loadMemories();
};

async function renderer_loadMemories(query = '') {
  const list = $('mp-list');
  if (!list) return;
  list.innerHTML = '<div style="padding:10px;color:var(--text-muted);font-size:11px;">Loading…</div>';
  try {
    let memories = [];
    if (query) {
      const resp = await fetch('http://127.0.0.1:8000/memory/search', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ query, top_k: 20 })
      });
      memories = (await resp.json()).results || [];
    } else {
      const resp = await fetch('http://127.0.0.1:8000/memory/all?limit=30');
      memories = (await resp.json()).memories || [];
    }
    list.innerHTML = '';
    if (!memories.length) {
      list.innerHTML = '<div style="padding:10px;color:var(--text-muted);font-size:11px;">No memories yet.</div>';
      return;
    }
    memories.forEach(m => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.innerHTML = `
        <span class="memory-type-badge">${m.type}</span>
        <span class="memory-content">${m.content.substring(0,120)}${m.content.length>120?'…':''}</span>
        <button class="memory-del-btn" onclick="renderer_deleteMemory(${m.id},this)">🗑</button>`;
      list.appendChild(item);
    });
  } catch { list.innerHTML = '<div style="padding:10px;color:var(--pink);font-size:11px;">Failed to load memories</div>'; }
}

window.renderer_deleteMemory = async function(id, btn) {
  try {
    await fetch(`http://127.0.0.1:8000/memory/${id}`, { method:'DELETE' });
    btn.closest('.memory-item').remove();
    state.memoryCount = Math.max(0, state.memoryCount - 1);
    if (DOM.memoryPillCount) DOM.memoryPillCount.textContent = `${state.memoryCount} memories`;
  } catch { showToast('Delete failed','error'); }
};

window.renderer_searchMemory = async () => {
  await renderer_loadMemories($('mp-search')?.value?.trim());
};

// ════════════════════════════════════════════════════════════
// PREDICTIVE SUGGESTIONS
// ════════════════════════════════════════════════════════════

async function loadSuggestions() {
  try {
    const emotion = window.nexonCurrentEmotion?.name?.toLowerCase() || 'neutral';
    const resp    = await fetch(`http://127.0.0.1:8000/predict/suggestions?emotion=${emotion}`);
    const data    = await resp.json();
    renderSuggestions(data.suggestions || []);
  } catch { /* non-critical */ }
}

function renderSuggestions(suggestions) {
  if (!DOM.suggestionsList) return;
  DOM.suggestionsList.innerHTML = '';
  suggestions.forEach(s => {
    const pill = document.createElement('div');
    pill.className = 'suggestion-pill';
    pill.innerHTML = `<span>🔮</span><span style="flex:1;font-size:11px;">${s.text.substring(0,60)}${s.text.length>60?'…':''}</span><span class="suggestion-conf">${Math.round(s.confidence*100)}%</span>`;
    pill.addEventListener('click', () => {
      if (DOM.chatInput) DOM.chatInput.value = s.intent?.replace(/_/g,' ') || s.text.replace(/Want me.*/,'').trim();
      DOM.chatInput?.focus();
    });
    DOM.suggestionsList.appendChild(pill);
  });
}

// ════════════════════════════════════════════════════════════
// SCREEN READER
// ════════════════════════════════════════════════════════════

window.renderer_readScreen = async function() {
  showToast('📷 Capturing screen…','info',2000);
  try {
    const resp = await fetch('http://127.0.0.1:8000/screen/read', {
      method:'POST', body: new URLSearchParams({ question: DOM.chatInput?.value || '' })
    });
    const data = await resp.json();
    if (data.success) {
      appendMessage('assistant',
        `🖥️ **Screen captured** (${data.detected_type})\n\n**Understanding:** ${data.understanding}${data.answer ? '\n\n**Answer:** '+data.answer : ''}`,
        null,'',true);
    } else {
      showToast(data.message || 'Screen read failed','error');
    }
  } catch { showToast('Screen read failed — install pytesseract','error'); }
};

// ════════════════════════════════════════════════════════════
// PERSONALITY & MACROS
// ════════════════════════════════════════════════════════════

window.renderer_showStyleProfile = async function() {
  try {
    const resp = await fetch(`http://127.0.0.1:8000/personality/${state.userId}`);
    const data = await resp.json();
    appendMessage('assistant', data.summary || 'No profile yet.', null,'',true);
  } catch { showToast('Failed to load profile','error'); }
};

window.renderer_showMacros = async function() {
  try {
    const resp   = await fetch('http://127.0.0.1:8000/macros');
    const data   = await resp.json();
    const macros = data.macros || [];
    if (!macros.length) {
      appendMessage('assistant',
        '🕹️ **No gesture macros yet.**\n\nCreate one by saying:\n*"Create gesture macro: THUMBS UP → send daily standup email"*',
        null,'',true);
      return;
    }
    const list = macros.map(m => `• **${m.gesture_name}** → "${m.macro_name}" (run ${m.run_count}×)`).join('\n');
    appendMessage('assistant', `🕹️ **Gesture Macros:**\n\n${list}`, null,'',true);
  } catch { showToast('Failed to load macros','error'); }
};

window.renderer_toggleCamera = function() {
  const video = $('camera-video');
  if (!video) return;
  const hidden = video.style.opacity === '0';
  video.style.opacity = hidden ? '1' : '0';
};

// ════════════════════════════════════════════════════════════
// CHAT MESSAGES
// ════════════════════════════════════════════════════════════

function appendWelcomeMessage() {
  appendMessage('assistant',
    '👋 **NEXON v2** is ready!\n\n🧠 Memory • 🔮 Predictive AI • 👁 Gaze tracking • 🎭 Style learning\n\nSay **"Hey NEXON"** or type anything below.',
    null,'',false);
}

function appendMessage(role, text, actionData=null, emotion='', animate=true) {
  if (!DOM.chatMessages) return;

  // Always clean context prefix from display
  const displayText = cleanDisplayText(text);
  if (!displayText) return;

  const row    = document.createElement('div');
  row.className= `message-row ${role==='user'?'user-row':'assistant-row'}`;

  const avatar      = document.createElement('div');
  avatar.className  = 'msg-avatar';
  avatar.textContent= role==='user'?'👤':'🤖';

  const bubble     = document.createElement('div');
  bubble.className = `msg-bubble ${role==='user'?'user-bubble':'assistant-bubble'}`;

  // Emotion tag for user messages
  if (role==='user' && emotion && !['neutral',''].includes(emotion.toLowerCase())) {
    const tag = document.createElement('div');
    tag.className   = 'msg-emotion-tag';
    const emap = {happy:'😊',sad:'😢',angry:'😠',surprised:'😮',fearful:'😨',disgusted:'😒',neutral:'😐'};
    tag.textContent = `${emap[emotion.toLowerCase()]||'😐'} ${emotion.toLowerCase()} mood`;
    bubble.appendChild(tag);
  }

  const textEl     = document.createElement('div');
  textEl.className = 'msg-text';
  textEl.innerHTML = renderMarkdown(displayText);

  const timeEl     = document.createElement('div');
  timeEl.className   = 'msg-time';
  timeEl.textContent = formatTime(new Date());

  bubble.appendChild(textEl);
  if (actionData) { const b = buildBadge(actionData); if (b) bubble.appendChild(b); }
  bubble.appendChild(timeEl);

  row.appendChild(avatar); row.appendChild(bubble);
  if (!animate) row.style.animation = 'none';

  DOM.chatMessages.appendChild(row);
  scrollToBottom();
}

function buildBadge(actionData) {
  const action = actionData?.action || actionData;
  if (!action?.type) return null;
  const badge   = document.createElement('div');
  const success = actionData.success !== false;
  badge.className   = `action-badge ${success?'badge-success':'badge-error'}`;
  badge.textContent = `${success?'⚡':'⚠️'} ${action.type.replace(/_/g,' ')}`;
  return badge;
}

function showTyping() {
  removeTyping();
  const row = document.createElement('div');
  row.className = 'message-row assistant-row'; row.id = 'typing-indicator';
  row.innerHTML = `<div class="msg-avatar">🤖</div><div class="msg-bubble assistant-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>`;
  DOM.chatMessages?.appendChild(row); scrollToBottom();
}
function removeTyping() { $('typing-indicator')?.remove(); }
function scrollToBottom() { requestAnimationFrame(() => { if (DOM.chatMessages) DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight; }); }

// ════════════════════════════════════════════════════════════
// SEND MESSAGE — KEY FIX: sends original_text to backend
// ════════════════════════════════════════════════════════════

async function sendMessage(text) {
  if (!text?.trim() || !state.activeSession) return;
  text = text.trim();
  if (DOM.chatInput) DOM.chatInput.value = '';

  const ctx = getCurrentEmotionContext();

  // Show user message WITHOUT context prefix
  appendMessage('user', text, null, ctx.emotion.toLowerCase());

  state.commandCount++;
  if (DOM.statCommands) DOM.statCommands.textContent = state.commandCount;

  // Build enriched prompt for LLM but keep original for display/DB
  const { enrichedText, originalText } = buildEnrichedPrompt(text, ctx);

  showTyping();

  try {
    // Send enriched text to LLM, but backend stores originalText
    const response = await window.nexonAPI.chat(
      enrichedText,                     // LLM sees context
      state.activeSession.id,
      state.language,
      ctx.emotion.toLowerCase(),
      state.mode
    );

    removeTyping();

    // Show parallel dashboard if multiple tasks
    if (response.parallel_tasks?.length > 1 && window.nexonParallel) {
      window.nexonParallel.displayRestResult(response.action);
    }

    // Show clean response (no JSON)
    appendMessage('assistant', response.response, response.action);

    if (response.suggestions?.length) renderSuggestions(response.suggestions);

    // Avatar talks
    if (window.nexonAvatar) {
      window.nexonAvatar.startTalking();
      const duration = Math.min(6000, response.response.length * 50);
      setTimeout(() => window.nexonAvatar?.stopTalking(), duration);
    }

    if (window.nexonSphere)   window.nexonSphere.setState('assistant');
    if (window.nexonWaveform) window.nexonWaveform.setMode('assistant');

    if (state.mode !== 'text') speakText(response.response, state.language);

    loadMemoryStats();
    await loadSessions();

    setTimeout(() => {
      if (window.nexonSphere)   window.nexonSphere.setState('idle');
      if (window.nexonWaveform) window.nexonWaveform.setMode('idle');
    }, 4000);

  } catch (err) {
    removeTyping();
    appendMessage('assistant',
      `❌ ${err.message}\n\nMake sure Ollama is running:\n\`ollama serve\`\n\`ollama pull llama3.2:3b\``);
    setConnectionStatus('disconnected');
  }
}

// ════════════════════════════════════════════════════════════
// VOICE RECORDER
// ════════════════════════════════════════════════════════════

function initRecorder() {
  if (!window.NexonVoiceRecorder) return;
  state.recorder = new window.NexonVoiceRecorder({
    onTranscript: async (text, lang, isWakeWord, stressData) => {
      if (stressData) updateVoiceStressUI(stressData);
      const transcriptEl = $('stat-transcript');
      if (transcriptEl) { transcriptEl.textContent = text.substring(0,25)+(text.length>25?'…':''); transcriptEl.title=text; }
      if (state.mode==='text' && !isWakeWord) return;
      if (DOM.chatInput) DOM.chatInput.value = text;
      await sendMessage(text);
    },
    onStateChange: recState => updateMicUI(recState),
    onError      : msg => { showToast(msg,'error'); updateMicUI('idle'); }
  });
  state.recorder.setLanguage(state.language);
}

function updateVoiceStressUI(stressData) {
  const stress = stressData?.stress_level || 0;
  state.voiceStress = stress;
  if (DOM.statStress) DOM.statStress.textContent = `${stress}%`;
  const fill = $('vsb-fill'), val = $('vsb-value'), emo = $('vsb-emotion');
  if (fill) { fill.style.width=`${stress}%`; fill.className=`${stress>65?'stress-high':stress>35?'stress-medium':'stress-low'}`; fill.id='vsb-fill'; }
  if (val)  val.textContent = `${stress}%`;
  if (emo)  emo.textContent = stressData?.voice_emotion || 'calm';
  const stressEl = $('ecs-stress');
  if (stressEl) {
    if (stress>65)      { stressEl.textContent=`🔥 ${stress}% stress`; stressEl.className='stress-high'; stressEl.id='ecs-stress'; }
    else if (stress>35) { stressEl.textContent=`⚠️ ${stress}% tense`; stressEl.className='stress-medium'; stressEl.id='ecs-stress'; }
    else                stressEl.textContent = '';
  }
}

function updateMicUI(recState) {
  const btn=DOM.micBtn, label=DOM.micLabel, icon=DOM.micIcon;
  if (!btn) return;
  btn.classList.remove('recording','processing');
  switch(recState) {
    case 'recording'  : btn.classList.add('recording');  if(label)label.textContent='LISTENING…'; if(icon)icon.textContent='🔴'; break;
    case 'processing' : btn.classList.add('processing'); if(label)label.textContent='PROCESSING…';if(icon)icon.textContent='⏳'; break;
    default           : if(label)label.textContent='TAP TO SPEAK'; if(icon)icon.textContent='🎙️';
  }
}

// ════════════════════════════════════════════════════════════
// TTS
// ════════════════════════════════════════════════════════════

function speakText(text, language='en') {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const clean = cleanDisplayText(text)
    .replace(/\*\*(.*?)\*\*/g,'$1').replace(/\*(.*?)\*/g,'$1')
    .replace(/```[\s\S]*?```/g,'').replace(/`(.*?)`/g,'$1')
    .replace(/^#+\s+/gm,'').substring(0,500);
  if (!clean.trim()) return;
  const utter   = new SpeechSynthesisUtterance(clean);
  const voices  = window.speechSynthesis.getVoices();
  utter.voice   = voices.find(v=>v.lang.startsWith(language==='hi'?'hi':'en'))||voices[0];
  utter.rate=1.0; utter.pitch=1.0; utter.volume=1.0;
  utter.onstart = () => { if(window.nexonWaveform)window.nexonWaveform.setMode('assistant'); };
  utter.onend   = () => {
    if(window.nexonWaveform)window.nexonWaveform.setMode('idle');
    if(window.nexonSphere)window.nexonSphere.setState('idle');
    if(window.nexonAvatar)window.nexonAvatar.stopTalking();
  };
  window.speechSynthesis.speak(utter);
}

// ════════════════════════════════════════════════════════════
// LANGUAGE & MODE
// ════════════════════════════════════════════════════════════

function setLanguage(lang) {
  state.language = lang;
  if (state.recorder) state.recorder.setLanguage(lang);
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.toggle('active', b.dataset.lang===lang));
  safeSetPreference('language', lang);
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode===mode));
  const voiceOnly = mode==='voice';
  if (DOM.chatInput) {
    DOM.chatInput.disabled    = voiceOnly;
    DOM.chatInput.placeholder = voiceOnly ? 'Voice mode — use the mic button above' : 'Message NEXON… (Enter to send)';
  }
}

// ════════════════════════════════════════════════════════════
// EVENT BINDING
// ════════════════════════════════════════════════════════════

function bindEvents() {
  DOM.sendBtn?.addEventListener('click', () => sendMessage(DOM.chatInput?.value||''));
  DOM.chatInput?.addEventListener('keydown', e => { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage(DOM.chatInput.value);} });
  DOM.micBtn?.addEventListener('click', () => {
    if (state.mode==='text'){showToast('Switch to Voice or Hybrid mode first','info'); return;}
    state.recorder?.toggle();
  });
  DOM.newChatLeft?.addEventListener('click',  createNewSession);
  DOM.newChatRight?.addEventListener('click', createNewSession);
  document.querySelectorAll('.lang-btn').forEach(b => b.addEventListener('click',()=>setLanguage(b.dataset.lang)));
  document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click',()=>setMode(b.dataset.mode)));
  DOM.attachBtn?.addEventListener('click', async () => {
    const p = await window.nexonAPI?.openFile();
    if (p && DOM.chatInput) { DOM.chatInput.value=`Analyze this file: ${p}`; DOM.chatInput.focus(); }
  });
  $('mp-search')?.addEventListener('keydown', e => { if(e.key==='Enter') renderer_searchMemory(); });
}

// ════════════════════════════════════════════════════════════
// UTILITIES
// ════════════════════════════════════════════════════════════

function renderMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,'<a href="$2" target="_blank">$1</a>')
    .replace(/^#{1,3}\s+(.+)$/gm,'<strong>$1</strong>')
    .replace(/\n/g,'<br>');
}
function formatTime(d) { return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }
function showToast(msg,type='info',duration=3000) {
  const c=$('toast-container'); if(!c)return;
  const t=document.createElement('div'); t.className=`toast ${type}`; t.textContent=msg;
  c.appendChild(t); setTimeout(()=>t.remove(),duration);
}
async function safeGetPreference(key) { try{const r=await window.nexonAPI?.getPreference(key);return r?.value||null;}catch{return null;} }
async function safeSetPreference(k,v) { try{await window.nexonAPI?.setPreference(k,v);}catch{} }

// ════════════════════════════════════════════════════════════
// BOOT
// ════════════════════════════════════════════════════════════
let _booted = false;
function boot() {
  if (_booted) return;
  _booted = true;
  setTimeout(initNexon, 500);
}
window.addEventListener('DOMContentLoaded', boot);
if (document.readyState==='complete'||document.readyState==='interactive') boot();