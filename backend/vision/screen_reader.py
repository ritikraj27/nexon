# backend/vision/screen_reader.py
# ============================================================
# NEXON Screen Visual Context Understanding
# Captures the screen, OCRs it, and uses LLM to understand
# and act on what's visible — without user describing it.
#
# "Summarize what's on my screen"
# "Fix the bug you can see in my code"
# "Reply to the email I'm looking at"
# ============================================================

import os
import re
import asyncio
import tempfile
import platform
import subprocess
from datetime import datetime
from typing import Dict, Optional

from backend.config import SCREENSHOT_DIR
from backend.llm_engine import nexon_llm

PLATFORM = platform.system()


class ScreenReader:
    """
    Captures screen content and uses multimodal understanding
    to extract text, context, and actionable information.

    Pipeline:
    1. Take screenshot (pyautogui or OS native)
    2. OCR with pytesseract
    3. LLM interprets content + user question
    4. Returns structured understanding

    Works entirely locally — no images sent to cloud.
    """

    async def read_screen(
        self,
        question     : Optional[str] = None,
        window_title : Optional[str] = None,
        region       : Optional[tuple] = None,
    ) -> Dict:
        """
        Capture and understand screen content.

        Args:
            question     : What the user wants to know about the screen.
            window_title : Capture specific window (partial name match).
            region       : (x, y, w, h) region to capture, or None for full screen.
        Returns:
            {
                screenshot_path : str,
                ocr_text        : str,
                understanding   : str,   # LLM interpretation
                detected_type   : str,   # email|code|document|browser|terminal|other
                action_suggested: str,   # Suggested NEXON action
                entities        : dict   # Extracted emails, URLs, filenames etc.
            }
        """
        # Step 1: Take screenshot
        screenshot_path = await self._take_screenshot(window_title, region)
        if not screenshot_path:
            return {"success": False, "message": "Could not take screenshot"}

        # Step 2: OCR
        ocr_text = await self._run_ocr(screenshot_path)

        if not ocr_text.strip():
            return {
                "success"        : True,
                "screenshot_path": screenshot_path,
                "ocr_text"       : "",
                "understanding"  : "Screen content could not be read (no text detected).",
                "detected_type"  : "other",
                "action_suggested": "",
                "entities"       : {},
            }

        # Step 3: LLM understanding
        understanding, detected_type, action_suggested = await self._llm_understand(
            ocr_text, question
        )

        # Step 4: Entity extraction
        entities = self._extract_entities(ocr_text)

        return {
            "success"        : True,
            "screenshot_path": screenshot_path,
            "ocr_text"       : ocr_text[:3000],
            "understanding"  : understanding,
            "detected_type"  : detected_type,
            "action_suggested": action_suggested,
            "entities"       : entities,
        }

    async def _take_screenshot(
        self,
        window_title: Optional[str] = None,
        region      : Optional[tuple] = None
    ) -> Optional[str]:
        """Take a screenshot and return the file path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"screen_read_{timestamp}.png"
        path      = os.path.join(SCREENSHOT_DIR, filename)

        try:
            import pyautogui
            if region:
                x, y, w, h = region
                ss = pyautogui.screenshot(region=(x, y, w, h))
            else:
                ss = pyautogui.screenshot()
            ss.save(path)
            return path
        except ImportError:
            pass

        # OS native fallback
        try:
            if PLATFORM == "Darwin":
                subprocess.run(["screencapture", "-x", path], check=True, timeout=5)
            elif PLATFORM == "Linux":
                subprocess.run(["scrot", path], check=True, timeout=5)
            elif PLATFORM == "Windows":
                ps = (
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.Screen]::PrimaryScreen | "
                    f"ForEach-Object {{ "
                    f"$bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width, $_.Bounds.Height); "
                    f"$g = [System.Drawing.Graphics]::FromImage($bmp); "
                    f"$g.CopyFromScreen($_.Bounds.Location, [System.Drawing.Point]::Empty, $_.Bounds.Size); "
                    f"$bmp.Save('{path}') }}"
                )
                subprocess.run(["powershell", "-Command", ps], check=True, timeout=10)

            return path if os.path.exists(path) else None
        except Exception as e:
            print(f"[ScreenReader] Screenshot failed: {e}")
            return None

    async def _run_ocr(self, image_path: str) -> str:
        """Run OCR on screenshot using pytesseract."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._ocr_sync, image_path)

    def _ocr_sync(self, image_path: str) -> str:
        """Synchronous OCR (CPU-bound)."""
        try:
            import pytesseract
            from PIL import Image, ImageEnhance, ImageFilter

            img = Image.open(image_path)

            # Preprocess for better OCR
            img = img.convert("L")  # Grayscale
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)

            # Scale up small screenshots
            w, h = img.size
            if w < 1200:
                img = img.resize((w * 2, h * 2), Image.LANCZOS)

            text = pytesseract.image_to_string(
                img,
                config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ !@#$%^&*()_+-=[]{}|;:,.<>?/\\\"\\'\\n\\t"
            )
            return text.strip()
        except ImportError:
            return ""
        except Exception as e:
            print(f"[ScreenReader] OCR error: {e}")
            return ""

    async def _llm_understand(
        self,
        ocr_text: str,
        question: Optional[str],
    ) -> tuple:
        """Use LLM to interpret screen content and suggest actions."""
        prompt = f"""
Analyze this text extracted from a screenshot and provide:
1. A concise understanding of what's on screen (1-2 sentences)
2. The type of content (one of: email|code|document|browser|terminal|spreadsheet|other)
3. A suggested NEXON action if appropriate (or empty string if none)

{f'User question: {question}' if question else ''}

Screen text:
{ocr_text[:2000]}

Respond in this exact JSON format:
{{"understanding": "...", "type": "...", "action": "..."}}
"""
        try:
            raw = await nexon_llm.generate_response(prompt, language="en", max_tokens=300)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            import json
            data = json.loads(raw)
            return (
                data.get("understanding", "Content analyzed."),
                data.get("type", "other"),
                data.get("action", ""),
            )
        except Exception:
            # Fallback without LLM
            detected = self._detect_content_type(ocr_text)
            return f"Screen shows {detected} content.", detected, ""

    def _detect_content_type(self, text: str) -> str:
        """Simple rule-based content type detection."""
        t = text.lower()
        if any(w in t for w in ["def ", "class ", "import ", "function ", "const ", "var ", "return "]):
            return "code"
        if any(w in t for w in ["from:", "to:", "subject:", "cc:", "reply"]):
            return "email"
        if any(w in t for w in ["http", "www.", ".com", "browser"]):
            return "browser"
        if any(w in t for w in ["$", "ls", "cd", "git ", "npm ", "pip ", "python"]):
            return "terminal"
        return "document"

    def _extract_entities(self, text: str) -> Dict:
        """Extract entities (emails, URLs, filenames) from OCR text."""
        return {
            "emails"   : re.findall(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', text),
            "urls"     : re.findall(r'https?://[^\s]+', text),
            "filenames": re.findall(r'\b[\w\-]+\.(pdf|docx|txt|csv|py|js|html|json)\b', text, re.I),
            "dates"    : re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text),
            "phones"   : re.findall(r'\b\+?\d[\d\s\-]{7,}\d\b', text),
        }

    async def answer_about_screen(self, question: str) -> Dict:
        """
        One-shot: take screenshot, OCR, and answer a specific question.

        Args:
            question : What the user wants to know about the screen.
        Returns:
            Full screen reading result with targeted answer.
        """
        result = await self.read_screen(question=question)
        if not result.get("success"):
            return result

        if question and result.get("ocr_text"):
            answer = await nexon_llm.generate_response(
                f"Based on this screen content, answer: '{question}'\n\n"
                f"Screen content:\n{result['ocr_text'][:2000]}",
                language="en"
            )
            result["answer"] = answer

        return result


# Singleton
screen_reader = ScreenReader()