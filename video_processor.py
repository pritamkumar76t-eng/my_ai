"""Video processor - extracts frames from video and reads Hindi text overlay via OCR."""
import re
import os
import sys
import logging
import tempfile
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)


def _import_cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def _import_easyocr():
    try:
        import easyocr
        return easyocr
    except ImportError:
        return None


def _import_numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


class VideoProcessor:
    """Extract Hindi text overlay from video frames (1-6 seconds) using OCR."""

    def __init__(self):
        self.cv2 = _import_cv2()
        self.easyocr = _import_easyocr()
        self.np = _import_numpy()
        self._ocr_reader = None

        self.cv2_available = self.cv2 is not None
        self.ocr_available = self.easyocr is not None and self.np is not None

        if not self.cv2_available:
            logger.warning("OpenCV not available")
        if not self.ocr_available:
            logger.warning("EasyOCR/NumPy not available")

    def _get_ocr_reader(self):
        if self._ocr_reader is None and self.ocr_available:
            try:
                logger.info("Loading EasyOCR (Hindi + English)...")
                self._ocr_reader = self.easyocr.Reader(['hi', 'en'], gpu=False, verbose=False)
                logger.info("EasyOCR loaded!")
            except Exception as e:
                logger.error(f"Failed to load EasyOCR: {e}")
                self.ocr_available = False
        return self._ocr_reader

    def is_video_link(self, url: str) -> bool:
        if not url:
            return False
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lower()
        video_exts = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.ts', '.m3u8')
        return any(path.endswith(ext) for ext in video_exts) or '/stream/' in path or '/video/' in path

    def extract_text_from_video(self, video_url: str, start_sec: int = 1, end_sec: int = 6) -> dict:
        result = {
            'text': '',
            'all_texts': [],
            'source': 'none',
            'confidence': 0,
            'error': None,
        }

        if not self.cv2_available or not self.ocr_available:
            result['error'] = 'OCR libraries not available'
            return result

        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(suffix='.mp4')
            os.close(fd)

            logger.info(f"Downloading video snippet from: {video_url}")
            req = urllib.request.Request(video_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(5 * 1024 * 1024)
                with open(temp_path, 'wb') as f:
                    f.write(data)

            logger.info(f"Downloaded to {temp_path}, extracting frames...")

            cap = self.cv2.VideoCapture(temp_path)
            if not cap.isOpened():
                result['error'] = 'Could not open video'
                return result

            fps = cap.get(self.cv2.CAP_PROP_FPS) or 25
            all_texts = []
            reader = self._get_ocr_reader()

            if not reader:
                result['error'] = 'OCR reader failed to load'
                return result

            for sec in range(start_sec, end_sec + 1):
                frame_num = int(sec * fps)
                cap.set(self.cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()

                if not ret or frame is None:
                    continue

                frame_rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)

                try:
                    ocr_results = reader.readtext(frame_rgb, detail=0, paragraph=False)
                    if ocr_results:
                        text = ' '.join(ocr_results)
                        all_texts.append({
                            'second': sec,
                            'text': text,
                            'length': len(text),
                        })
                        logger.info(f"Frame at {sec}s: {text[:100]}")
                except Exception as e:
                    logger.warning(f"OCR error at {sec}s: {e}")

            cap.release()

            if all_texts:
                best = max(all_texts, key=lambda x: x['length'])
                result['text'] = best['text']
                result['all_texts'] = all_texts
                result['source'] = 'video_ocr'
                result['confidence'] = 85
                logger.info(f"Best OCR text: {best['text'][:150]}")
            else:
                result['error'] = 'No text found in video frames'

        except Exception as e:
            logger.error(f"Video processing error: {e}")
            result['error'] = str(e)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

        return result

    def cross_verify_with_video(self, text_result: dict, video_text: str, matcher) -> dict:
        from difflib import SequenceMatcher

        text_subject = text_result.get('subject', '')
        text_chapter = text_result.get('chapter', '')

        if not video_text or len(video_text) < 3:
            return {
                'subject': text_subject,
                'chapter': text_chapter,
                'confidence': text_result.get('confidence', 0),
                'lecture': text_result.get('lecture'),
                'verified': False,
                'reason': 'no_video_text',
            }

        video_match = matcher.find_best_match(video_text, top_n=1)

        if video_match['subject'] and video_match['chapter']:
            subject_match = text_subject.lower() == video_match['subject'].lower()
            chapter_sim = SequenceMatcher(
                None,
                text_chapter.lower(),
                video_match['chapter'].lower()
            ).ratio()

            if subject_match and chapter_sim > 0.4:
                return {
                    'subject': text_subject,
                    'chapter': text_chapter,
                    'confidence': min(text_result.get('confidence', 0) + 25, 100),
                    'lecture': text_result.get('lecture'),
                    'verified': True,
                    'reason': 'text_video_match',
                    'video_chapter': video_match['chapter'],
                }
            elif chapter_sim > 0.3:
                return {
                    'subject': text_subject,
                    'chapter': text_chapter,
                    'confidence': min(text_result.get('confidence', 0) + 10, 90),
                    'lecture': text_result.get('lecture'),
                    'verified': True,
                    'reason': 'partial_match',
                    'video_chapter': video_match['chapter'],
                }
            else:
                return {
                    'subject': text_subject,
                    'chapter': text_chapter,
                    'confidence': max(text_result.get('confidence', 0) - 10, 30),
                    'lecture': text_result.get('lecture'),
                    'verified': False,
                    'reason': 'text_video_conflict',
                    'video_suggests': video_match['chapter'],
                    'warning': f'⚠️ Video shows: {video_match["chapter"]}',
                }

        return {
            'subject': text_subject,
            'chapter': text_chapter,
            'confidence': text_result.get('confidence', 0),
            'lecture': text_result.get('lecture'),
            'verified': False,
            'reason': 'video_unclear',
        }


def extract_urls(text: str) -> list:
    url_pattern = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+'
    )
    return url_pattern.findall(text)
