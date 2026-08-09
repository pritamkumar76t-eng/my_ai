"""Smart Text Parser - learns from repeated number patterns."""
import re
from collections import Counter


def parse_lecture_text(text: str, history_lectures: list = None) -> dict:
    result = {
        "index": None,
        "title": None,
        "quality": None,
        "lecture_number": None,
        "raw_title": None,
        "clean_title": None,
        "core_title": None,
    }

    # Extract Index
    index_match = re.search(r'[➭\-]\s*Index\s*[»›>]\s*(\S+)', text, re.IGNORECASE)
    if not index_match:
        index_match = re.search(r'Index\s*[:»›>]\s*(\S+)', text, re.IGNORECASE)
    if index_match:
        result["index"] = index_match.group(1).strip()

    # Extract Title
    title_match = re.search(r'[➭\-]\s*Title\s*[»›>]\s*(.*?)(?=[➭\-]|━━━━━|$)', text, re.IGNORECASE | re.DOTALL)
    if not title_match:
        title_match = re.search(r'Title\s*[:»›>]\s*(.*?)(?=\n\n|$)', text, re.IGNORECASE | re.DOTALL)

    raw_title = None
    if title_match:
        raw_title = title_match.group(1).strip()

    # If no title marker, use longest meaningful line
    if not raw_title:
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 10]
        if lines:
            raw_title = max(lines, key=len)

    if raw_title:
        result["raw_title"] = raw_title
        clean = _clean_title(raw_title)
        result["clean_title"] = clean
        result["title"] = clean
        result["core_title"] = _extract_core_words(clean)
        result["lecture_number"] = _detect_lecture_number(
            text, raw_title, clean, result.get("index"), history_lectures
        )

    # Extract Quality
    quality_match = re.search(r'[➭\-]\s*Quality\s*[»›>]\s*(\S+)', text, re.IGNORECASE)
    if not quality_match:
        quality_match = re.search(r'Quality\s*[:»›>]\s*(\S+)', text, re.IGNORECASE)
    if quality_match:
        result["quality"] = quality_match.group(1).strip()

    if not result["quality"]:
        res_match = re.search(r'(\d{3,4}x\d{3,4})', text)
        if res_match:
            result["quality"] = res_match.group(1)

    return result


def _clean_title(raw: str) -> str:
    clean = raw
    clean = re.sub(r'\.(mkv|mp4|avi|pdf|mov)', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bNO\s*DPP\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bNO\s*DPPS?\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\d{3,4}x\d{3,4}', '', clean)
    clean = re.sub(r'\b(20\d{2})\b', '', clean)
    clean = re.sub(r'\b(Hindi|English|Hinglish|HD|SD)\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _extract_core_words(clean: str) -> str:
    hindi_vowels = 'अआइईउऊएऐओऔंःािीुूेैोौ'
    words = clean.split()
    core = []
    for word in words:
        if len(word) <= 2:
            core.append(word)
        elif re.search(f'[aeiouAEIOU{hindi_vowels}]', word):
            core.append(word)
        elif re.search(r'[\u0966-\u096f0-9]', word):
            core.append(word)
    return ' '.join(core)


def _detect_lecture_number(full_text: str, raw_title: str, clean_title: str,
                           index: str, history_lectures: list) -> str:
    """Smart lecture number detection:
    1. Extract ALL numbers
    2. Filter out resolutions, years, index
    3. Find most frequent/repeated number
    4. Use history if available
    """
    all_nums = re.findall(r'\b(\d{1,3})\b', full_text)
    all_nums = [n.zfill(2) for n in all_nums]

    filtered = []
    for n in all_nums:
        if index and n.lstrip('0') == index.lstrip('0'):
            continue
        if n in ['480', '720', '854', '1080', '1280', '1920', '640', '360']:
            continue
        if len(n) == 4 and n.startswith('20'):
            continue
        filtered.append(n)

    if not filtered:
        return None

    counter = Counter(filtered)

    # If history available, prefer numbers that appear in history
    if history_lectures:
        for num, count in counter.most_common():
            if num in history_lectures:
                return num

    most_common = counter.most_common(1)[0]
    if most_common[1] >= 1:
        return most_common[0]

    return None
