# backend/agents/screen_agent.py
# ============================================================
# NEXON Screen & System Control Agent
# Handles screenshots, screen recording, app control,
# system settings (volume, brightness, wifi), clipboard.
# ============================================================

import os
import sys
import time
import subprocess
import platform
from datetime import datetime
from typing import Dict, List, Optional
from backend.config import SCREENSHOT_DIR, RECORDINGS_DIR, NEXON_HOME
from backend.llm_engine import nexon_llm

PLATFORM = platform.system()  # 'Darwin' | 'Windows' | 'Linux'


class ScreenAgent:
    """
    Screen and system control agent for NEXON.

    Capabilities:
    - Take screenshots (full screen, window, region).
    - Screen recording (start/stop).
    - OCR on screenshots using pytesseract.
    - Open/quit applications by name.
    - System controls: volume, brightness, wifi, bluetooth.
    - Focus mode / Do Not Disturb.
    - Clipboard read/write.
    - App usage monitoring.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        """Route screen/system intents to the appropriate handler."""
        handlers = {
            "take_screenshot" : self.take_screenshot,
            "screen_record"   : self.screen_record,
            "open_app"        : self.open_app,
            "system_control"  : self.system_control,
            "clipboard"       : self.clipboard_action,
            "ocr_screen"      : self.ocr_screenshot,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    # ──────────────────────────────────────────
    # Screenshot
    # ──────────────────────────────────────────

    async def take_screenshot(self, params: Dict, session_id: str) -> Dict:
        """
        Capture the screen and save to ~/NEXON/Screenshots/.

        Args:
            params: {
                region  (str)  : 'full'|'window'|'region' (default 'full').
                filename (str) : Output filename (auto-generated if not set).
                annotate (bool): Whether to open for annotation.
            }
        Returns:
            Action result with screenshot path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = params.get("filename", f"screenshot_{timestamp}.png")
        save_path = os.path.join(SCREENSHOT_DIR, filename)

        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)

            return {
                "success": True,
                "message": f"📸 Screenshot saved!\n`{save_path}`",
                "action" : {
                    "type"   : "screenshot_taken",
                    "details": {"path": save_path, "filename": filename}
                }
            }
        except ImportError:
            # Fallback: use OS-native screenshot tool
            return await self._native_screenshot(save_path)
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Screenshot failed: {str(e)}",
                "action" : {"type": "screenshot_taken", "details": {}, "error": str(e)}
            }

    async def _native_screenshot(self, save_path: str) -> Dict:
        """Use OS-native screenshot command as fallback."""
        try:
            if PLATFORM == "Darwin":
                subprocess.run(["screencapture", "-x", save_path], check=True)
            elif PLATFORM == "Windows":
                # PowerShell screenshot
                ps_cmd = (
                    f'Add-Type -AssemblyName System.Windows.Forms; '
                    f'[System.Windows.Forms.Screen]::PrimaryScreen | '
                    f'% {{ $bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width, $_.Bounds.Height); '
                    f'$g = [System.Drawing.Graphics]::FromImage($bmp); '
                    f'$g.CopyFromScreen($_.Bounds.Location, [System.Drawing.Point]::Empty, $_.Bounds.Size); '
                    f'$bmp.Save("{save_path}") }}'
                )
                subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            elif PLATFORM == "Linux":
                subprocess.run(["scrot", save_path], check=True)

            return {
                "success": True,
                "message": f"📸 Screenshot saved: `{save_path}`",
                "action" : {"type": "screenshot_taken", "details": {"path": save_path}}
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Native screenshot failed: {str(e)}",
                "action" : {}
            }

    # ──────────────────────────────────────────
    # Screen Recording
    # ──────────────────────────────────────────

    async def screen_record(self, params: Dict, session_id: str) -> Dict:
        """
        Start or stop screen recording.

        Args:
            params: {
                action   (str): 'start'|'stop'.
                duration (int): Max duration in seconds (default 60).
                filename (str): Output filename.
            }
        """
        action   = params.get("action", "start")
        filename = params.get("filename",
                              f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        save_path = os.path.join(RECORDINGS_DIR, filename)

        if action == "start":
            # macOS: use built-in screencapture
            if PLATFORM == "Darwin":
                subprocess.Popen(["screencapture", "-v", save_path])
                return {
                    "success": True,
                    "message": f"🎥 Screen recording started.\nSaving to: `{save_path}`\nSay 'stop recording' to stop.",
                    "action" : {"type": "screen_record_started", "details": {"path": save_path}}
                }
            else:
                return {
                    "success": True,
                    "message": "🎥 Screen recording started (stub — install OBS or ffmpeg for full support).",
                    "action" : {"type": "screen_record_started", "details": {}}
                }
        else:
            # Stop: send SIGTERM to screencapture or ffmpeg
            if PLATFORM == "Darwin":
                subprocess.run(["pkill", "-x", "screencapture"])
            return {
                "success": True,
                "message": f"🛑 Screen recording stopped.\nSaved to: `{save_path}`",
                "action" : {"type": "screen_record_stopped", "details": {"path": save_path}}
            }

    # ──────────────────────────────────────────
    # Open / Quit Applications
    # ──────────────────────────────────────────

    async def open_app(self, params: Dict, session_id: str) -> Dict:
        """
        Open an application by name.

        Args:
            params: {
                app_name (str): Application name (e.g., 'chrome', 'vscode').
                action   (str): 'open'|'quit'.
            }
        """
        app_name = params.get("app_name", "").lower().strip()
        action   = params.get("action", "open")

        # App name → executable/bundle mapping
        app_map_mac = {
            "chrome"     : "Google Chrome",
            "safari"     : "Safari",
            "firefox"    : "Firefox",
            "vscode"     : "Visual Studio Code",
            "code"       : "Visual Studio Code",
            "slack"      : "Slack",
            "zoom"       : "zoom.us",
            "teams"      : "Microsoft Teams",
            "discord"    : "Discord",
            "spotify"    : "Spotify",
            "terminal"   : "Terminal",
            "finder"     : "Finder",
            "notes"      : "Notes",
            "calendar"   : "Calendar",
            "mail"       : "Mail",
            "word"       : "Microsoft Word",
            "excel"      : "Microsoft Excel",
            "powerpoint" : "Microsoft PowerPoint",
            "whatsapp"   : "WhatsApp",
            "telegram"   : "Telegram",
        }

        app_map_win = {
            "chrome"     : "chrome.exe",
            "firefox"    : "firefox.exe",
            "vscode"     : "code.exe",
            "code"       : "code.exe",
            "slack"      : "slack.exe",
            "zoom"       : "zoom.exe",
            "teams"      : "teams.exe",
            "discord"    : "discord.exe",
            "spotify"    : "spotify.exe",
            "notepad"    : "notepad.exe",
            "explorer"   : "explorer.exe",
            "word"       : "winword.exe",
            "excel"      : "excel.exe",
            "powerpoint" : "powerpnt.exe",
            "calculator" : "calc.exe",
        }

        try:
            if action == "quit":
                if PLATFORM == "Darwin":
                    bundle = app_map_mac.get(app_name, app_name)
                    subprocess.run(["osascript", "-e", f'quit app "{bundle}"'])
                elif PLATFORM == "Windows":
                    exe = app_map_win.get(app_name, f"{app_name}.exe")
                    subprocess.run(["taskkill", "/f", "/im", exe])
                return {
                    "success": True,
                    "message": f"✅ Closed **{app_name}**.",
                    "action" : {"type": "app_quit", "details": {"app": app_name}}
                }

            # Open app
            if PLATFORM == "Darwin":
                bundle = app_map_mac.get(app_name, app_name.title())
                subprocess.Popen(["open", "-a", bundle])
            elif PLATFORM == "Windows":
                exe = app_map_win.get(app_name, f"{app_name}.exe")
                subprocess.Popen(["start", exe], shell=True)
            elif PLATFORM == "Linux":
                subprocess.Popen([app_name])

            return {
                "success": True,
                "message": f"✅ Opened **{app_name}**.",
                "action" : {"type": "app_opened", "details": {"app": app_name}}
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Could not open '{app_name}': {str(e)}",
                "action" : {"type": "app_opened", "details": {}, "error": str(e)}
            }

    # ──────────────────────────────────────────
    # System Controls
    # ──────────────────────────────────────────

    async def system_control(self, params: Dict, session_id: str) -> Dict:
        """
        Control system settings: volume, brightness, wifi, bluetooth, etc.

        Args:
            params: {
                control (str): 'volume'|'brightness'|'wifi'|'bluetooth'|
                               'sleep'|'shutdown'|'restart'|'dnd'.
                value   (any): The value to set (e.g., 50 for volume 50%).
                action  (str): 'on'|'off'|'set'|'toggle'.
            }
        """
        control = params.get("control", "").lower()
        value   = params.get("value", None)
        action  = params.get("action", "toggle")

        try:
            # ── Volume ──────────────────────
            if control == "volume":
                level = int(value or 50)
                if PLATFORM == "Darwin":
                    subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
                elif PLATFORM == "Windows":
                    # Using nircmd (optional) or PowerShell
                    ps = f"(New-Object -com Shell.Application).Windows() | % {{ $_.Document.Application.Volume = {level} }}"
                    subprocess.run(["powershell", "-Command", ps])
                return {
                    "success": True,
                    "message": f"🔊 Volume set to **{level}%**.",
                    "action" : {"type": "system_volume", "details": {"level": level}}
                }

            # ── Brightness ──────────────────
            elif control == "brightness":
                level = int(value or 50)
                if PLATFORM == "Darwin":
                    # Requires 'brightness' CLI: brew install brightness
                    subprocess.run(["brightness", str(level / 100)])
                return {
                    "success": True,
                    "message": f"☀️ Brightness set to **{level}%**.",
                    "action" : {"type": "system_brightness", "details": {"level": level}}
                }

            # ── WiFi ────────────────────────
            elif control == "wifi":
                if PLATFORM == "Darwin":
                    state = "on" if action == "on" else "off"
                    subprocess.run([
                        "networksetup", "-setairportpower", "en0", state
                    ])
                elif PLATFORM == "Windows":
                    state = "enable" if action == "on" else "disable"
                    subprocess.run(["netsh", "interface", "set", "interface",
                                    "Wi-Fi", state])
                return {
                    "success": True,
                    "message": f"📶 WiFi turned **{action}**.",
                    "action" : {"type": "system_wifi", "details": {"state": action}}
                }

            # ── Sleep / Shutdown / Restart ──
            elif control == "sleep":
                if PLATFORM == "Darwin":
                    subprocess.run(["pmset", "sleepnow"])
                elif PLATFORM == "Windows":
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
                return {"success": True, "message": "💤 System going to sleep.",
                        "action": {"type": "system_sleep", "details": {}}}

            elif control == "shutdown":
                if PLATFORM == "Darwin":
                    subprocess.run(["sudo", "shutdown", "-h", "now"])
                elif PLATFORM == "Windows":
                    subprocess.run(["shutdown", "/s", "/t", "0"])
                return {"success": True, "message": "🔴 Shutting down...",
                        "action": {"type": "system_shutdown", "details": {}}}

            elif control == "restart":
                if PLATFORM == "Darwin":
                    subprocess.run(["sudo", "shutdown", "-r", "now"])
                elif PLATFORM == "Windows":
                    subprocess.run(["shutdown", "/r", "/t", "0"])
                return {"success": True, "message": "🔄 Restarting...",
                        "action": {"type": "system_restart", "details": {}}}

            else:
                return {
                    "success": False,
                    "message": f"Unknown system control: '{control}'. "
                               "Try: volume, brightness, wifi, sleep, shutdown, restart.",
                    "action" : {}
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"❌ System control failed: {str(e)}",
                "action" : {"error": str(e)}
            }

    # ──────────────────────────────────────────
    # Clipboard
    # ──────────────────────────────────────────

    async def clipboard_action(self, params: Dict, session_id: str) -> Dict:
        """
        Read from or write to the system clipboard.

        Args:
            params: {
                action  (str): 'read'|'write'|'clear'.
                content (str): Content to write (for 'write' action).
            }
        """
        action  = params.get("action", "read")
        content = params.get("content", "")

        try:
            import pyperclip
            if action == "write":
                pyperclip.copy(content)
                return {
                    "success": True,
                    "message": f"📋 Copied to clipboard: `{content[:80]}`",
                    "action" : {"type": "clipboard_write", "details": {"content": content}}
                }
            elif action == "clear":
                pyperclip.copy("")
                return {
                    "success": True,
                    "message": "📋 Clipboard cleared.",
                    "action" : {"type": "clipboard_clear", "details": {}}
                }
            else:  # read
                text = pyperclip.paste()
                return {
                    "success": True,
                    "message": f"📋 Clipboard contains:\n```\n{text[:500]}\n```",
                    "action" : {"type": "clipboard_read", "details": {"content": text}}
                }
        except ImportError:
            return {"success": False, "message": "pyperclip not installed.", "action": {}}

    # ──────────────────────────────────────────
    # OCR
    # ──────────────────────────────────────────

    async def ocr_screenshot(self, params: Dict, session_id: str) -> Dict:
        """
        Take a screenshot and extract text using OCR.

        Args:
            params: { translate_to (str): Optional target language for translation. }
        """
        # First take screenshot
        ss_result = await self.take_screenshot({}, session_id)
        if not ss_result["success"]:
            return ss_result

        path = ss_result["action"]["details"]["path"]

        try:
            import pytesseract
            from PIL import Image
            img  = Image.open(path)
            text = pytesseract.image_to_string(img)

            result_msg = f"🔍 **OCR Result:**\n```\n{text[:1000]}\n```"

            # Translate if requested
            translate_to = params.get("translate_to")
            if translate_to and text.strip():
                translated = await nexon_llm.generate_response(
                    f"Translate the following text to {translate_to}:\n\n{text}",
                    language="en"
                )
                result_msg += f"\n\n🌐 **Translation ({translate_to}):**\n{translated}"

            return {
                "success": True,
                "message": result_msg,
                "action" : {"type": "ocr_complete", "details": {"text": text, "path": path}}
            }
        except ImportError:
            return {
                "success": False,
                "message": "pytesseract or Pillow not installed. Run: pip install pytesseract Pillow",
                "action" : {}
            }

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {"success": False, "message": "Unknown screen action.", "action": {}}