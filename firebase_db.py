"""Firebase Database for learning, remembering, and correcting."""
import os
import json
import tempfile
import hashlib
from datetime import datetime
from collections import Counter

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False


class FirebaseDB:
    def __init__(self):
        self.db = None
        self.enabled = False
        self._init_firebase()

    def _init_firebase(self):
        if not FIREBASE_AVAILABLE:
            print("[Firebase] firebase-admin not installed.")
            return

        cred_json = os.environ.get("FIREBASE_CREDENTIALS", "")
        if not cred_json:
            print("[Firebase] FIREBASE_CREDENTIALS not set.")
            return

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(cred_json)
                cred_path = f.name

            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.enabled = True
            print("[Firebase] Connected!")
        except Exception as e:
            print(f"[Firebase] Error: {e}")

    def _text_hash(self, text: str) -> str:
        normalized = ' '.join(text.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()

    def _text_fingerprint(self, text: str) -> str:
        import re
        words = re.findall(r'[\u0900-\u097F\w]+', text.lower())
        meaningful = [w for w in words if len(w) > 2]
        fingerprint = ' '.join(sorted(meaningful[:8]))
        return fingerprint

    def save_correction(self, user_id: int, raw_text: str,
                        correct_subject: str, correct_chapter: str,
                        correct_lecture: str = None):
        if not self.enabled or not self.db:
            return False

        fingerprint = self._text_fingerprint(raw_text)
        text_hash = self._text_hash(raw_text)

        correction_doc = {
            "user_id": user_id,
            "raw_text": raw_text,
            "text_hash": text_hash,
            "fingerprint": fingerprint,
            "correct_subject": correct_subject,
            "correct_chapter": correct_chapter,
            "correct_lecture": correct_lecture,
            "timestamp": datetime.utcnow(),
            "usage_count": 1,
        }

        existing = self._find_existing_correction(user_id, fingerprint)
        if existing:
            doc_id = existing["id"]
            current_count = existing.get("usage_count", 1)
            self.db.collection("corrections").document(doc_id).update({
                "correct_subject": correct_subject,
                "correct_chapter": correct_chapter,
                "correct_lecture": correct_lecture,
                "timestamp": datetime.utcnow(),
                "usage_count": current_count + 1,
                "raw_text": raw_text,
            })
        else:
            self.db.collection("corrections").add(correction_doc)

        self.db.collection("users").document(str(user_id)).collection("corrections").add({
            "text_preview": raw_text[:100],
            "correct_subject": correct_subject,
            "correct_chapter": correct_chapter,
            "timestamp": datetime.utcnow(),
        })

        return True

    def _find_existing_correction(self, user_id: int, fingerprint: str) -> dict:
        if not self.enabled or not self.db:
            return None

        docs = (
            self.db.collection("corrections")
            .where("user_id", "==", user_id)
            .where("fingerprint", "==", fingerprint)
            .limit(1)
            .stream()
        )

        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def find_correction(self, user_id: int, text: str) -> dict:
        if not self.enabled or not self.db:
            return None

        fingerprint = self._text_fingerprint(text)
        text_hash = self._text_hash(text)

        docs = (
            self.db.collection("corrections")
            .where("user_id", "==", user_id)
            .where("text_hash", "==", text_hash)
            .limit(1)
            .stream()
        )

        for doc in docs:
            data = doc.to_dict()
            return {
                "subject": data.get("correct_subject"),
                "chapter": data.get("correct_chapter"),
                "lecture": data.get("correct_lecture"),
                "confidence": 100,
                "from_correction": True,
            }

        docs = (
            self.db.collection("corrections")
            .where("user_id", "==", user_id)
            .where("fingerprint", "==", fingerprint)
            .limit(1)
            .stream()
        )

        for doc in docs:
            data = doc.to_dict()
            return {
                "subject": data.get("correct_subject"),
                "chapter": data.get("correct_chapter"),
                "lecture": data.get("correct_lecture"),
                "confidence": 95,
                "from_correction": True,
            }

        return None

    def get_user_top_subjects(self, user_id: int, top_n: int = 3) -> list:
        if not self.enabled or not self.db:
            return []
        user_doc = self.db.collection("users").document(str(user_id)).get()
        if not user_doc.exists:
            return []
        subjects = user_doc.to_dict().get("subjects", {})
        sorted_subjects = sorted(subjects.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_subjects[:top_n]]

    def get_learned_lecture_pattern(self, user_id: int) -> dict:
        if not self.enabled or not self.db:
            return {}
        docs = (
            self.db.collection("interactions")
            .where("user_id", "==", user_id)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(20)
            .stream()
        )
        lecture_nums = []
        for doc in docs:
            data = doc.to_dict()
            lec = data.get("parsed_lecture_number")
            if lec:
                lecture_nums.append(lec)
        if not lecture_nums:
            return {}
        counter = Counter(lecture_nums)
        most_common = counter.most_common(1)[0]
        return {
            "most_common_lecture": most_common[0],
            "frequency": most_common[1],
            "all_lectures": lecture_nums[:10],
        }

    def boost_confidence_with_history(self, user_id: int, current_match: dict) -> dict:
        if not self.enabled or not self.db:
            return current_match
        top_subjects = self.get_user_top_subjects(user_id)
        current_subject = current_match.get("subject", "")
        if current_subject in top_subjects:
            current_match["confidence"] = min(current_match.get("confidence", 0) + 15, 100)
            current_match["history_boosted"] = True
        return current_match

    def save_interaction(self, user_id: int, raw_text: str, parsed: dict, match: dict):
        if not self.enabled or not self.db:
            return
        doc = {
            "user_id": user_id,
            "raw_text": raw_text,
            "parsed_index": parsed.get("index"),
            "parsed_title": parsed.get("title"),
            "parsed_quality": parsed.get("quality"),
            "parsed_lecture_number": parsed.get("lecture_number"),
            "matched_subject": match.get("subject"),
            "matched_chapter": match.get("chapter"),
            "confidence": match.get("confidence"),
            "timestamp": datetime.utcnow(),
        }
        self.db.collection("interactions").add(doc)
        self._update_user_stats(user_id, match)

    def _update_user_stats(self, user_id: int, match: dict):
        user_ref = self.db.collection("users").document(str(user_id))
        user_doc = user_ref.get()
        subject = match.get("subject", "Unknown")
        chapter = match.get("chapter", "Unknown")
        if user_doc.exists:
            data = user_doc.to_dict()
            subjects = data.get("subjects", {})
            chapters = data.get("chapters", {})
            subjects[subject] = subjects.get(subject, 0) + 1
            chapters[chapter] = chapters.get(chapter, 0) + 1
            user_ref.update({
                "subjects": subjects,
                "chapters": chapters,
                "last_active": datetime.utcnow(),
            })
        else:
            user_ref.set({
                "subjects": {subject: 1},
                "chapters": {chapter: 1},
                "first_seen": datetime.utcnow(),
                "last_active": datetime.utcnow(),
            })
