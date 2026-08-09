"""Text parser for extracting lecture metadata."""
import re


def parse_lecture_text(text: str) -> dict:
    """
    Parse lecture info from text format like:
    ➭ Index » 004
    ➭ Title » कोशिका जीवन की इकाई 01  कोशिका सिद्धांत  NO DPP 854x480.mkv
    ➭ Quality » 854x480
    """
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
    if index_match:
        result["index"] = index_match.group(1).strip()

    # Extract Title - multi-line support
    title_match = re.search(r'[➭\-]\s*Title\s*[»›>]\s*(.*?)(?=[➭\-]|━━━━━|$)', text, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = title_match.group(1).strip()
        result["raw_title"] = raw_title

        clean = raw_title
        clean = re.sub(r'\.mkv|\.mp4|\.avi|\.pdf', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'NO\s*DPP', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'NO\s*DPPS?', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\d{3,4}x\d{3,4}', '', clean)
        clean = re.sub(r'\b\d{4}\b', '', clean)
        clean = re.sub(r'Hindi|English|Hinglish', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\s+', ' ', clean).strip()
        result["clean_title"] = clean
        result["title"] = clean

        # Extract lecture number from title (e.g. "01", "Lec 05", "Lecture 3")
        lec_patterns = [
            r'\bLec\s*(\d+)\b',
            r'\bLecture\s*(\d+)\b',
            r'\bLEC\s*(\d+)\b',
            r'\b(\d{2,3})\s+(?=[^\d])',
        ]
        for pattern in lec_patterns:
            lec_match = re.search(pattern, clean, re.IGNORECASE)
            if lec_match:
                result["lecture_number"] = lec_match.group(1).zfill(2)
                break

        # Extract core title - keep meaningful words only
        hindi_vowels = r'अआइईउऊएऐओऔंःािीुूेैोौ'
        words = clean.split()
        core_words = []
        for word in words:
            if len(word) <= 2:
                core_words.append(word)
            elif re.search(f'[aeiouAEIOU{hindi_vowels}]', word):
                core_words.append(word)
            elif re.search(r'[०-९0-9]', word):
                core_words.append(word)

        result["core_title"] = ' '.join(core_words)

    # Extract Quality
    quality_match = re.search(r'[➭\-]\s*Quality\s*[»›>]\s*(\S+)', text, re.IGNORECASE)
    if quality_match:
        result["quality"] = quality_match.group(1).strip()
    else:
        res_match = re.search(r'(\d{3,4}x\d{3,4})', text)
        if res_match:
            result["quality"] = res_match.group(1)

    return result
