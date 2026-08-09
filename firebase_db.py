"""Firebase Database for learning & remembering text formats."""
import os
import json
import tempfile
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
            "format_pattern": self._detect_format_pattern(raw_text),
        }
        self.db.collection("interactions").add(doc)
        self._update_user_stats(user_id, match)

    def _detect_format_pattern(self, text: str) -> str:
        patterns = []
        if "Index" in text or "इंडेक्स" in text:
            patterns.append("has_index")
        if "Title" in text or "टाइटल" in text or "➭" in text:
            patterns.append("has_title_marker")
        if "Quality" in text or "क्वालिटी" in text:
            patterns.append("has_quality")
        if "854x480" in text or "1280x720" in text:
            patterns.append("has_resolution")
        if ".mkv" in text or ".mp4" in text:
            patterns.append("has_extension")
        return "|".join(patterns) if patterns else "unknown"

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
