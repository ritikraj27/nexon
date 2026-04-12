// frontend/electron/main.js — FIXED VERSION
// ============================================================
// Fix: uploadAudio() now correctly sends multipart FormData
//      with the audio file field named 'audio' (was missing)
// Fix: Added biometric face recognition on startup
// Fix: Better error handling throughout
// ============================================================

const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs   = require('fs');

const BACKEND_URL  = 'http://127.0.0.1:8000';
const PRELOAD_PATH = path.join(__dirname, 'preload.js');
const INDEX_PATH   = path.join(__dirname, '..', 'renderer', 'index.html');
const SPLASH_PATH  = path.join(__dirname, '..', 'renderer', 'splash.html');

let mainWindow  = null;
let splashWindow= null;

// ── Backend HTTP helper ───────────────────────────────────────

async function backendRequest(endpoint, method = 'GET', body = null) {
  const url     = `${BACKEND_URL}${endpoint}`;
  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) options.body = JSON.stringify(body);

  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Backend error ${response.status}: ${errorText}`);
    }
    return await response.json();
  } catch (err) {
    console.error(`[NEXON IPC] Request to ${endpoint} failed:`, err.message);
    throw err;
  }
}

// ── Audio upload — FIXED ──────────────────────────────────────
// The 422 error was caused by incorrect FormData construction.
// Node's built-in fetch doesn't handle Buffer→Blob the same way
// as browsers. We use the undici FormData or construct raw multipart.

async function uploadAudio(endpoint, audioBuffer, language = '', format = 'webm') {
  const url = `${BACKEND_URL}${endpoint}`;

  // Build raw multipart/form-data manually for maximum compatibility
  const boundary = `----NexonBoundary${Date.now()}`;
  const CRLF     = '\r\n';

  // Helper to create a form part
  const makeFilePart = (fieldName, fileName, mimeType, data) => {
    const header = (
      `--${boundary}${CRLF}` +
      `Content-Disposition: form-data; name="${fieldName}"; filename="${fileName}"${CRLF}` +
      `Content-Type: ${mimeType}${CRLF}${CRLF}`
    );
    return Buffer.concat([
      Buffer.from(header, 'utf8'),
      data,
      Buffer.from(CRLF, 'utf8'),
    ]);
  };

  const makeTextPart = (fieldName, value) => {
    const part = (
      `--${boundary}${CRLF}` +
      `Content-Disposition: form-data; name="${fieldName}"${CRLF}${CRLF}` +
      `${value}${CRLF}`
    );
    return Buffer.from(part, 'utf8');
  };

  const audioData = Buffer.from(audioBuffer);
  const mimeType  = format === 'wav' ? 'audio/wav' : 'audio/webm;codecs=opus';

  const body = Buffer.concat([
    makeFilePart('audio', `recording.${format}`, mimeType, audioData),
    makeTextPart('language', language || ''),
    makeTextPart('format', format),
    makeTextPart('analyze_stress', 'true'),
    Buffer.from(`--${boundary}--${CRLF}`, 'utf8'),
  ]);

  try {
    const response = await fetch(url, {
      method : 'POST',
      headers: {
        'Content-Type'  : `multipart/form-data; boundary=${boundary}`,
        'Content-Length': body.length.toString(),
      },
      body,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Transcription error ${response.status}: ${errorText}`);
    }
    return await response.json();
  } catch (err) {
    console.error('[NEXON] uploadAudio failed:', err.message);
    throw err;
  }
}

// ── Splash (biometric) window ─────────────────────────────────

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width          : 500,
    height         : 600,
    resizable      : false,
    frame          : false,
    transparent    : true,
    alwaysOnTop    : true,
    backgroundColor: '#0a0e1a',
    webPreferences : {
      preload         : PRELOAD_PATH,
      nodeIntegration : false,
      contextIsolation: true,
    },
  });

  splashWindow.loadFile(SPLASH_PATH);
  splashWindow.on('closed', () => { splashWindow = null; });
}

// ── Main window ───────────────────────────────────────────────

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width          : 1600,
    height         : 1000,
    minWidth       : 1200,
    minHeight      : 800,
    title          : 'NEXON — AI Operating System',
    backgroundColor: '#0a0e1a',
    titleBarStyle  : 'hiddenInset',
    frame          : process.platform !== 'darwin',
    show           : false,  // Show only after ready-to-show
    webPreferences : {
      preload            : PRELOAD_PATH,
      nodeIntegration    : false,
      contextIsolation   : true,
      enableRemoteModule : false,
      webSecurity        : false,
    },
  });

  mainWindow.loadFile(INDEX_PATH);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── App lifecycle ─────────────────────────────────────────────

app.whenReady().then(async () => {
  // Check if backend is available and if biometric is set up
  let useBiometric = false;
  try {
    const health = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) });
    if (health.ok) {
      const profilesResp = await fetch(`${BACKEND_URL}/auth/profiles`);
      const profilesData = await profilesResp.json();
      const profiles     = profilesData.profiles || [];
      // Only show splash if there are enrolled face profiles (not just default)
      const hasEnrolledFaces = profiles.some(p => p.user_id !== 'default' && p.face_enrolled);
      useBiometric = hasEnrolledFaces;
    }
  } catch (e) {
    console.log('[NEXON] Backend not ready for biometric check:', e.message);
  }

  if (useBiometric) {
    createSplashWindow();
  } else {
    createMainWindow();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ── IPC: Splash → Main transition ────────────────────────────

ipcMain.handle('nexon:biometricPassed', async (event, { userId, name }) => {
  // Face recognized — close splash, open main window with user context
  if (splashWindow) {
    splashWindow.close();
  }
  createMainWindow();
  // Send user info to main window once it's ready
  if (mainWindow) {
    mainWindow.webContents.once('did-finish-load', () => {
      mainWindow.webContents.send('nexon:userIdentified', { userId, name });
    });
  }
  return { success: true };
});

ipcMain.handle('nexon:biometricSkip', async () => {
  // Skip face recognition — open main as default user
  if (splashWindow) splashWindow.close();
  createMainWindow();
  return { success: true };
});

// ── IPC: Chat ─────────────────────────────────────────────────

ipcMain.handle('nexon:chat', async (event, payload) => {
  return await backendRequest('/chat', 'POST', payload);
});

// ── IPC: Audio transcription — FIXED ─────────────────────────

ipcMain.handle('nexon:transcribeAudio', async (event, payload) => {
  const { audioBuffer, language = '', format = 'webm' } = payload;
  const buffer = Buffer.from(audioBuffer);
  return await uploadAudio('/transcribe', buffer, language, format);
});

// ── IPC: Sessions ─────────────────────────────────────────────

ipcMain.handle('nexon:getSessions', async () => {
  return await backendRequest('/sessions', 'GET');
});

ipcMain.handle('nexon:createSession', async (event, payload) => {
  return await backendRequest('/sessions', 'POST', payload);
});

ipcMain.handle('nexon:deleteSession', async (event, payload) => {
  return await backendRequest(`/sessions/${payload.session_id}`, 'DELETE');
});

ipcMain.handle('nexon:switchSession', async (event, payload) => {
  return await backendRequest(`/sessions/${payload.session_id}/switch`, 'POST');
});

ipcMain.handle('nexon:getHistory', async (event, payload) => {
  return await backendRequest(`/history/${payload.session_id}`, 'GET');
});

// ── IPC: System ───────────────────────────────────────────────

ipcMain.handle('nexon:health', async () => {
  return await backendRequest('/health', 'GET');
});

ipcMain.handle('nexon:tts', async (event, payload) => {
  return await backendRequest('/tts', 'POST', payload);
});

ipcMain.handle('nexon:screenshot', async () => {
  return await backendRequest('/agent/screenshot', 'POST');
});

ipcMain.handle('nexon:setPreference', async (event, payload) => {
  return await backendRequest('/preferences', 'POST', payload);
});

ipcMain.handle('nexon:getPreference', async (event, payload) => {
  return await backendRequest(`/preferences/${payload.key}`, 'GET');
});

ipcMain.handle('nexon:openFile', async () => {
  const result = await dialog.showOpenDialog(mainWindow || BrowserWindow.getFocusedWindow(), {
    properties: ['openFile'],
    filters   : [
      { name: 'All Files',   extensions: ['*'] },
      { name: 'Documents',   extensions: ['pdf', 'docx', 'txt'] },
      { name: 'Data Files',  extensions: ['csv', 'xlsx', 'json'] },
      { name: 'Images',      extensions: ['png', 'jpg', 'jpeg'] },
    ]
  });
  return result.canceled ? null : result.filePaths[0];
});

// ── IPC: Biometric ────────────────────────────────────────────

ipcMain.handle('nexon:recognizeFace', async (event, payload) => {
  // payload.imageBuffer = ArrayBuffer of JPEG image
  const buffer   = Buffer.from(payload.imageBuffer);
  const boundary = `----BiometricBoundary${Date.now()}`;
  const CRLF     = '\r\n';

  const body = Buffer.concat([
    Buffer.from(`--${boundary}${CRLF}Content-Disposition: form-data; name="image"; filename="face.jpg"${CRLF}Content-Type: image/jpeg${CRLF}${CRLF}`, 'utf8'),
    buffer,
    Buffer.from(`${CRLF}--${boundary}--${CRLF}`, 'utf8'),
  ]);

  const response = await fetch(`${BACKEND_URL}/auth/recognize`, {
    method : 'POST',
    headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
    body,
  });
  return await response.json();
});

ipcMain.handle('nexon:getProfiles', async () => {
  return await backendRequest('/auth/profiles', 'GET');
});

ipcMain.handle('nexon:switchProfile', async (event, { userId }) => {
  return await backendRequest(`/auth/switch/${userId}`, 'POST');
});