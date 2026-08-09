"""Chapter and Subject matcher using fuzzy string matching + Firebase history."""
import os
import re
from difflib import SequenceMatcher


class ChapterMatcher:
    def __init__(self, data_dir="./data"):
        self.subjects = {}
        self.chapters = {}
        self.all_topics = []
        self._load_data(data_dir)

    def _load_data(self, data_dir):
        if not os.path.exists(data_dir):
            print(f"[Warning] Data directory not found: {data_dir}")
            return

        for filename in os.listdir(data_dir):
            if not filename.endswith('.txt'):
                continue

            subject = filename.replace('.txt', '').strip()
            filepath = os.path.join(data_dir, filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            self.subjects[subject] = content
            self.chapters[subject] = []

            lines = content.splitlines()
            current_chapter = None
            current_topics = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                is_chapter = False
                if line.startswith('★') or line.startswith('@'):
                    is_chapter = True
                    chapter_name = re.sub(r'^[★@]\s*', '', line).strip()
                elif line.startswith('यहाँ') or line.startswith('यह') or 'सूची' in line or 'प्रारूप' in line:
                    continue
                elif current_chapter is None and len(line) > 3:
                    is_chapter = True
                    chapter_name = line

                if is_chapter:
                    if current_chapter:
                        self.chapters[subject].append((current_chapter, current_topics))
                    current_chapter = chapter_name
                    current_topics = [chapter_name]
                elif current_chapter:
                    current_topics.append(line)
                    self.all_topics.append((line, subject, current_chapter))

            if current_chapter:
                self.chapters[subject].append((current_chapter, current_topics))

    def _similarity(self, a: str, b: str) -> float:
        a = a.lower().strip()
        b = b.lower().strip()
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _token_match_score(self, text: str, topic: str) -> float:
        text_tokens = set(re.findall(r'\w+', text.lower()))
        topic_tokens = set(re.findall(r'\w+', topic.lower()))

        if not text_tokens or not topic_tokens:
            return 0.0

        intersection = text_tokens & topic_tokens
        union = text_tokens | topic_tokens

        jaccard = len(intersection) / len(union) if union else 0

        phrase_bonus = 0
        if topic.lower() in text.lower():
            phrase_bonus = 0.35
        elif any(word in text.lower() for word in topic.lower().split() if len(word) > 3):
            phrase_bonus = 0.12

        return min(jaccard + phrase_bonus, 1.0)

    def _score_text_against_chapter(self, text: str, chapter_name: str, topics: list) -> float:
        chap_sim = self._similarity(text, chapter_name)
        chap_token = self._token_match_score(text, chapter_name)

        best_topic_sim = 0
        best_topic_token = 0
        for topic in topics[:30]:
            t_sim = self._similarity(text, topic)
            t_token = self._token_match_score(text, topic)
            if t_sim > best_topic_sim:
                best_topic_sim = t_sim
            if t_token > best_topic_token:
                best_topic_token = t_token

        score = max(chap_sim, best_topic_sim) * 0.30 + max(chap_token, best_topic_token) * 0.70
        return min(score, 1.0)

    def find_best_match(self, text: str, core_text: str = None,
                        user_history_subjects: list = None, top_n: int = 3) -> dict:
        if not text:
            return {"subject": "Unknown", "chapter": "Unknown", "confidence": 0, "candidates": []}

        texts_to_try = [text]
        if core_text and core_text != text:
            texts_to_try.append(core_text)

        half_match = re.match(r'(.+?)(?:\s+\d+\s+|$)', text)
        if half_match and half_match.group(1).strip() != text:
            texts_to_try.append(half_match.group(1).strip())

        all_candidates = []

        for subject, chapter_list in self.chapters.items():
            for chapter_name, topics in chapter_list:
                best_score = 0
                for t in texts_to_try:
                    score = self._score_text_against_chapter(t, chapter_name, topics)
                    if score > best_score:
                        best_score = score

                if best_score > 0.04:
                    all_candidates.append({
                        "subject": subject,
                        "chapter": chapter_name,
                        "score": best_score,
                    })

        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        if not all_candidates:
            return {"subject": "Unknown", "chapter": "Unknown", "confidence": 0, "candidates": []}

        # Boost score for subjects in user's history
        if user_history_subjects:
            for cand in all_candidates:
                if cand["subject"] in user_history_subjects:
                    cand["score"] = min(cand["score"] + 0.15, 1.0)

            all_candidates.sort(key=lambda x: x["score"], reverse=True)

        best = all_candidates[0]
        return {
            "subject": best["subject"],
            "chapter": best["chapter"],
            "confidence": round(best["score"] * 100, 1),
            "candidates": all_candidates[:top_n]
        }
