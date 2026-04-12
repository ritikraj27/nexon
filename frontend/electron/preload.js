// frontend/electron/preload.js — FIXED VERSION
// Adds biometric methods for splash screen face recognition

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nexonAPI', {

  // ── Chat ──────────────────────────────────────────────────
  chat: (text, sessionId, language='en', emotion='neutral', mode='text') =>
    ipcRenderer.invoke('nexon:chat', { text, session_id:sessionId, language, emotion, mode }),

  // ── Speech ────────────────────────────────────────────────
  transcribeAudio: (audioBuffer, language='', format='webm') =>
    ipcRenderer.invoke('nexon:transcribeAudio', { audioBuffer, language, format }),

  speak: (text, language='en') =>
    ipcRenderer.invoke('nexon:tts', { text, language }),

  // ── Sessions ──────────────────────────────────────────────
  getSessions   : ()           => ipcRenderer.invoke('nexon:getSessions'),
  createSession : (language)   => ipcRenderer.invoke('nexon:createSession', { language }),
  deleteSession : (sessionId)  => ipcRenderer.invoke('nexon:deleteSession', { session_id:sessionId }),
  switchSession : (sessionId)  => ipcRenderer.invoke('nexon:switchSession', { session_id:sessionId }),
  getHistory    : (sessionId)  => ipcRenderer.invoke('nexon:getHistory',    { session_id:sessionId }),

  // ── System ────────────────────────────────────────────────
  health      : ()       => ipcRenderer.invoke('nexon:health'),
  screenshot  : ()       => ipcRenderer.invoke('nexon:screenshot'),
  openFile    : ()       => ipcRenderer.invoke('nexon:openFile'),
  setPreference: (k, v)  => ipcRenderer.invoke('nexon:setPreference', { key:k, value:v }),
  getPreference: (k)     => ipcRenderer.invoke('nexon:getPreference', { key:k }),

  // ── Biometric (used by splash.html) ───────────────────────
  recognizeFace   : (imageBuffer) => ipcRenderer.invoke('nexon:recognizeFace', { imageBuffer }),
  getProfiles     : ()            => ipcRenderer.invoke('nexon:getProfiles'),
  switchProfile   : (userId)      => ipcRenderer.invoke('nexon:switchProfile', { userId }),
  biometricPassed : (data)        => ipcRenderer.invoke('nexon:biometricPassed', data),
  biometricSkip   : ()            => ipcRenderer.invoke('nexon:biometricSkip'),

  // ── Events from main process ──────────────────────────────
  onUserIdentified: (callback) => ipcRenderer.on('nexon:userIdentified', (_, data) => callback(data)),

});