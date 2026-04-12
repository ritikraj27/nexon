# backend/auth/biometric.py
# ============================================================
# NEXON Local Biometric Authentication
# On-device face recognition — zero cloud uploads.
# Each recognized face maps to a user profile with its own
# memory graph, personality profile, and preferences.
#
# Install: pip install face-recognition (requires dlib + cmake)
# Falls back to name-based profiles if face-recognition unavailable.
# ============================================================

import os
import json
import pickle
import base64
import tempfile
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from backend.config import NEXON_HOME

PROFILES_DIR = os.path.join(NEXON_HOME, "biometric")
os.makedirs(PROFILES_DIR, exist_ok=True)

PROFILES_FILE  = os.path.join(PROFILES_DIR, "profiles.json")
ENCODINGS_FILE = os.path.join(PROFILES_DIR, "encodings.pkl")

# Try face_recognition library
_FR_AVAILABLE = False
try:
    import face_recognition
    import numpy as np
    _FR_AVAILABLE = True
    print("[Biometric] face_recognition loaded ✓")
except ImportError:
    print("[Biometric] face_recognition not available — using name-based profiles")


class BiometricAuth:
    """
    Local face recognition authentication for NEXON.

    Profiles are stored entirely on device:
    - Face encodings: ~/NEXON/biometric/encodings.pkl
    - Profile data:   ~/NEXON/biometric/profiles.json

    Each user profile has its own:
    - Memory graph (separate DB namespace)
    - Personality style preferences
    - Chat history
    - Custom agent configurations

    If face_recognition is not installed, falls back to
    a simple active-profile system (manually switched).
    """

    def __init__(self):
        self.profiles  = self._load_profiles()
        self.encodings = self._load_encodings()
        self.active_user_id = "default"

    # ──────────────────────────────────────────
    # PROFILE MANAGEMENT
    # ──────────────────────────────────────────

    def _load_profiles(self) -> Dict:
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "default": {
                "user_id"   : "default",
                "name"      : "User",
                "created_at": datetime.utcnow().isoformat(),
                "last_seen" : datetime.utcnow().isoformat(),
                "login_count": 0,
                "avatar"    : "👤",
            }
        }

    def _save_profiles(self):
        with open(PROFILES_FILE, "w") as f:
            json.dump(self.profiles, f, indent=2)

    def _load_encodings(self) -> Dict[str, list]:
        """Load face encodings from disk."""
        if not _FR_AVAILABLE:
            return {}
        if os.path.exists(ENCODINGS_FILE):
            try:
                with open(ENCODINGS_FILE, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        return {}

    def _save_encodings(self):
        if not _FR_AVAILABLE:
            return
        with open(ENCODINGS_FILE, "wb") as f:
            pickle.dump(self.encodings, f)

    def create_profile(
        self,
        name   : str,
        avatar : str = "👤",
        user_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a new user profile.

        Args:
            name    : Display name.
            avatar  : Emoji avatar.
            user_id : Custom ID (auto-generated if not set).
        Returns:
            New profile dict.
        """
        uid = user_id or f"user_{len(self.profiles) + 1}_{datetime.utcnow().strftime('%Y%m%d')}"
        profile = {
            "user_id"    : uid,
            "name"       : name,
            "created_at" : datetime.utcnow().isoformat(),
            "last_seen"  : datetime.utcnow().isoformat(),
            "login_count": 0,
            "avatar"     : avatar,
        }
        self.profiles[uid] = profile
        self._save_profiles()
        return profile

    def list_profiles(self) -> List[Dict]:
        """Return all user profiles."""
        return list(self.profiles.values())

    def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile and its face encoding."""
        if user_id == "default":
            return False
        if user_id in self.profiles:
            del self.profiles[user_id]
            self._save_profiles()
        if user_id in self.encodings:
            del self.encodings[user_id]
            self._save_encodings()
        return True

    # ──────────────────────────────────────────
    # FACE ENROLLMENT
    # ──────────────────────────────────────────

    async def enroll_face(
        self,
        image_bytes: bytes,
        user_id    : str,
        image_format: str = "jpg"
    ) -> Dict:
        """
        Enroll a face image for a user profile.

        Args:
            image_bytes  : Raw image data (JPEG/PNG).
            user_id      : Profile to associate with.
            image_format : Image format hint.
        Returns:
            {success: bool, message: str, face_count: int}
        """
        if not _FR_AVAILABLE:
            return {
                "success": False,
                "message": "face_recognition library not installed. Run: pip install face-recognition",
                "face_count": 0
            }

        if user_id not in self.profiles:
            return {"success": False, "message": "Profile not found", "face_count": 0}

        # Write to temp file
        suffix = f".{image_format}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._encode_face_sync, tmp_path, user_id
            )
            return result
        finally:
            os.unlink(tmp_path)

    def _encode_face_sync(self, image_path: str, user_id: str) -> Dict:
        """Synchronous face encoding (CPU-bound, runs in thread)."""
        try:
            img      = face_recognition.load_image_file(image_path)
            encodings = face_recognition.face_encodings(img)

            if not encodings:
                return {"success": False, "message": "No face detected in image. Please try again.", "face_count": 0}

            if len(encodings) > 1:
                return {"success": False, "message": "Multiple faces detected. Please use an image with only your face.", "face_count": len(encodings)}

            # Store encoding (average of multiple shots for robustness)
            existing = self.encodings.get(user_id, [])
            existing.append(encodings[0].tolist())

            # Keep max 5 encodings per user (different angles/lighting)
            if len(existing) > 5:
                existing = existing[-5:]

            self.encodings[user_id] = existing
            self._save_encodings()

            profile = self.profiles[user_id]
            profile["face_enrolled"] = True
            profile["face_count"]    = len(existing)
            self._save_profiles()

            return {
                "success"   : True,
                "message"   : f"✅ Face enrolled for {profile['name']} ({len(existing)} sample{'s' if len(existing) > 1 else ''})",
                "face_count": len(existing)
            }

        except Exception as e:
            return {"success": False, "message": f"Enrollment failed: {str(e)}", "face_count": 0}

    # ──────────────────────────────────────────
    # FACE RECOGNITION
    # ──────────────────────────────────────────

    async def recognize_face(
        self,
        image_bytes : bytes,
        image_format: str = "jpg",
        tolerance   : float = 0.55,
    ) -> Dict:
        """
        Recognize a face from an image and return matching profile.

        Args:
            image_bytes  : Raw image data.
            image_format : Format hint.
            tolerance    : Match tolerance (lower = stricter).
        Returns:
            {
                recognized  : bool,
                user_id     : str,
                name        : str,
                confidence  : float,
                profile     : dict
            }
        """
        if not _FR_AVAILABLE or not self.encodings:
            return {
                "recognized": False,
                "user_id"   : self.active_user_id,
                "name"      : self.profiles.get(self.active_user_id, {}).get("name", "User"),
                "confidence": 0.0,
                "profile"   : self.profiles.get(self.active_user_id, {}),
                "fallback"  : True,
            }

        suffix = f".{image_format}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._recognize_sync, tmp_path, tolerance
            )
            return result
        finally:
            os.unlink(tmp_path)

    def _recognize_sync(self, image_path: str, tolerance: float) -> Dict:
        """Synchronous face recognition."""
        try:
            unknown_img = face_recognition.load_image_file(image_path)
            unknown_enc = face_recognition.face_encodings(unknown_img)

            if not unknown_enc:
                return {"recognized": False, "user_id": "default", "confidence": 0.0}

            unknown_vec = unknown_enc[0]
            best_match  = None
            best_conf   = 0.0

            for user_id, stored_encodings in self.encodings.items():
                for stored_enc in stored_encodings:
                    stored_vec = np.array(stored_enc)
                    distance   = face_recognition.face_distance([stored_vec], unknown_vec)[0]
                    confidence = max(0.0, 1.0 - distance)

                    if confidence > best_conf and distance <= tolerance:
                        best_conf  = confidence
                        best_match = user_id

            if best_match:
                profile = self.profiles.get(best_match, {})
                # Update last seen
                profile["last_seen"]   = datetime.utcnow().isoformat()
                profile["login_count"] = profile.get("login_count", 0) + 1
                self._save_profiles()
                self.active_user_id = best_match

                return {
                    "recognized": True,
                    "user_id"   : best_match,
                    "name"      : profile.get("name", "Unknown"),
                    "confidence": round(float(best_conf), 3),
                    "profile"   : profile,
                }

            return {"recognized": False, "user_id": "default", "confidence": 0.0}

        except Exception as e:
            return {"recognized": False, "user_id": "default", "confidence": 0.0, "error": str(e)}

    def switch_profile(self, user_id: str) -> Dict:
        """Manually switch active user profile."""
        if user_id not in self.profiles:
            return {"success": False, "message": "Profile not found"}
        self.active_user_id = user_id
        profile = self.profiles[user_id]
        profile["last_seen"] = datetime.utcnow().isoformat()
        self._save_profiles()
        return {"success": True, "profile": profile}

    @property
    def active_profile(self) -> Dict:
        """Get the currently active user profile."""
        return self.profiles.get(self.active_user_id, self.profiles.get("default", {}))


# Singleton
biometric_auth = BiometricAuth()