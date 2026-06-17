import re
from typing import List, Dict, Tuple, Any
from extractor.logger import logger

# Matches an EPIC-style token: 2-3 letters + 6-7 digits (8-10 chars total)
_EPIC_TOKEN_RE = re.compile(r'^[A-Z]{2,3}[0-9]{6,7}$', re.IGNORECASE)

# Words that appear as photo placeholder text — must never be treated as a voter name
_PHOTO_NOISE = {
    "available", "avalable", "avalible", "availble", "photo", "not available",
    "photo available", "photo avalable", "photo not available", "image", "picture",
    "no photo", "photo unavailable",
}

# Common OCR mis-reads for field labels
_AGE_KEYWORDS = re.compile(
    r'\b(?:age|aqe|ag|a9e|aoe|a8e|a6e|ag\.|age\.|years?)\b',
    re.IGNORECASE
)
_GENDER_KEYWORDS = re.compile(
    r'\b(?:gender|sex|qender|gend|gen der|gander)\b',
    re.IGNORECASE
)

# Field keyword list for sl_no parsing exclusion
_SL_SKIP_KEYWORDS = [
    "name", "father", "husband", "mother", "wife", "house", "number",
    "no.", "age", "gender", "sex", "photo", "available", "avalable",
    "deleted", "expired", "relation", "status", "section", "part",
    "constituency", "assembly"
]


def parse_sl_no(text_lines: List[str]) -> str:
    """
    Extracts voter Serial Number. It is typically a standalone integer.
    Scans all lines and skips lines that belong to other fields or look like EPIC tokens.
    Rejects '0' as that is never a valid serial number.
    """
    for line in text_lines:
        stripped = line.strip()
        lower_line = stripped.lower()

        # Skip lines containing keywords of other fields
        if any(k in lower_line for k in _SL_SKIP_KEYWORDS):
            continue

        # Skip lines that look like an EPIC number
        if _EPIC_TOKEN_RE.match(stripped):
            continue

        # We expect a standalone number, e.g. "12" or "1" or "03"
        # Match only if the line has just digits and optional whitespace/punctuation
        if re.match(r'^\s*\d+[\s:.-]*$', stripped):
            cleaned = re.sub(r'[^\d]', '', stripped)
            if cleaned and len(cleaned) <= 4 and cleaned != "0":
                return cleaned

    return ""


def parse_epic_no(text_lines: List[str]) -> str:
    """
    Extracts EPIC Number.
    Karnataka EPICs are typically [A-Z]{3}[0-9]{6,7} (9 or 10 chars).
    Supports typos, spaces, and OCR noise.
    """
    epic_skip_lower = [
        "name", "father", "husband", "mother", "wife", "house", "number",
        "age", "gender", "sex", "photo", "available", "avalable", "availble",
        "avallab", "image", "picture"
    ]
    
    # 1. Clean and check tokens line-by-line first (up to first 4 lines of the card)
    for line in text_lines[:4]:
        line_stripped = line.strip()
        if not line_stripped:
            continue
            
        # Clean trailing slashes or typical boundary noise
        line_cleaned = re.sub(r'[/\\._\-\s]+$', '', line_stripped)
        
        # Split by whitespace
        tokens = line_cleaned.split()
        
        # Check individual tokens
        for tok in tokens:
            # Strip non-alphanumeric characters (like slashes, hyphens, etc.)
            tok_clean = re.sub(r'[^a-zA-Z0-9]', '', tok)
            tok_lower = tok_clean.lower()
            
            # Skip if token contains any of the forbidden keywords
            if any(k in tok_lower for k in epic_skip_lower):
                continue
                
            # EPIC check: length between 7 and 12, contains both letters and digits
            if 7 <= len(tok_clean) <= 12:
                has_letter = any(c.isalpha() for c in tok_clean)
                has_digit = any(c.isdigit() for c in tok_clean)
                if has_letter and has_digit:
                    # Check if the first 4 chars contain at least some letters
                    prefix = tok_clean[:4]
                    if sum(1 for c in prefix if c.isalpha()) >= 2:
                        return tok_clean.upper()
                        
        # 2. If no individual token matched, try combining adjacent non-keyword tokens in the line
        filtered_tokens = []
        for tok in tokens:
            tok_clean = re.sub(r'[^a-zA-Z0-9]', '', tok)
            tok_lower = tok_clean.lower()
            if not any(k in tok_lower for k in epic_skip_lower):
                filtered_tokens.append(tok_clean)
                
        if filtered_tokens:
            combined_toks = "".join(filtered_tokens)
            if 7 <= len(combined_toks) <= 12:
                has_letter = any(c.isalpha() for c in combined_toks)
                has_digit = any(c.isdigit() for c in combined_toks)
                if has_letter and has_digit:
                    prefix = combined_toks[:4]
                    if sum(1 for c in prefix if c.isalpha()) >= 2:
                        return combined_toks.upper()

    # 3. Fallback to regex search on combined text
    combined = " ".join(text_lines)
    # Primary regex: 2-3 capital letters followed by optional space and 6-7 digits
    primary = re.search(r'\b([A-Z]{2,3})\s*(\d{6,7})\b', combined, re.IGNORECASE)
    if primary:
        return f"{primary.group(1).upper()}{primary.group(2)}"

    # Flexible regex: 2-3 capital letters followed by optional space and 6-7 alphanumeric
    flexible = re.search(r'\b([A-Z]{2,3})\s*([A-Z0-9]{6,7})\b', combined, re.IGNORECASE)
    if flexible:
        val = f"{flexible.group(1).upper()}{flexible.group(2).upper()}"
        if any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            return val

    return ""


def _is_photo_noise(text: str) -> bool:
    """Returns True if the text is a photo placeholder (should not be treated as a name)."""
    clean = text.strip().lower()
    # Exact match against known noise words
    if clean in _PHOTO_NOISE:
        return True
    # Partial match: "photo" anywhere in a short string
    if "photo" in clean or "avalab" in clean or "availab" in clean or "avallab" in clean:
        return True
    return False



def is_relation_line(line: str) -> bool:
    """
    Determines if a given line contains relationship labels/prefixes or typos of them.
    Protects proper names like 'Gurumurthy' or 'Guruprasad' by using boundary checks.
    """
    lower_line = line.lower().strip()
    if ":" in line:
        left = line.split(":", 1)[0].lower().strip()
        relation_keywords = [
            "father", "husband", "mother", "wife", "relation", "guardian", "gurdian", "guru", "other",
            "fath", "husb", "moth", "wfe", "othr", "fater", "tather", "ather", "husoand", "nusoand", "hushand", "husban", "usband", "isband", "tusband"
        ]
        return any(k in left for k in relation_keywords)
    else:
        # If no colon separator, check for relation prefix preceding 'name' or typos
        return bool(re.search(
            r'\b(?:father|husband|mother|wife|gurus?|guardian|gurdian|relation|other|fath|husb|moth|wfe|othr|fater|tather|ather|husoand|nusoand|hushand|husban|usband|isband|tusband)s?(?:\'s)?\s*(?:name|nane|nmae|neme|nama)\b',
            lower_line
        ))


def parse_name(text_lines: List[str]) -> str:
    """
    Extracts voter name. Looks for lines containing "Name" and filters out relation names
    and photo placeholder noise text.
    """
    for line in text_lines:
        lower_line = line.lower()
        if any(n in lower_line for n in ["name", "nane", "nmae", "neme", "nama", "vame", "wame", "mane"]) and not is_relation_line(line):
            parts = line.split(":", 1)
            name_val = parts[1].strip() if len(parts) > 1 else line
            # Clean up the prefix "Name", "Nane", etc. if there is no colon
            if len(parts) <= 1:
                name_val = re.sub(r'^(?:name|nane|nmae|neme|nama|vame|wame|mane)\s*[:.\-–\s]*', '', name_val, flags=re.IGNORECASE).strip()
            name_val = re.sub(r'^[\s:.-]+', '', name_val).strip()

            # Reject photo noise
            if _is_photo_noise(name_val):
                continue
            # Reject empty or single-char
            if len(name_val) < 2:
                continue

            return name_val

    # Fallback to the first long alphabetical line that isn't a keyword or noise
    for line in text_lines:
        if not is_relation_line(line):
            lower_line = line.lower()
            skip_keywords = [
                "name", "nane", "nmae", "neme", "nama", "vame", "wame", "mane",
                "house", "number", "no.", "age", "gender", "sex", "deleted", "section", "part",
                "assembly", "constituency"
            ]
            if not any(k in lower_line for k in skip_keywords):
                cleaned_line = line.strip()
                if (len(cleaned_line) > 3
                        and not re.match(r'^[A-Z]{3}\d{7}$', cleaned_line, re.IGNORECASE)
                        and not cleaned_line.isdigit()
                        and not _is_photo_noise(cleaned_line)):
                    return cleaned_line

    return ""


def parse_relation(text_lines: List[str]) -> Tuple[str, str]:
    """
    Extracts relationship type and relative name.
    Supports any relationship label before a separator (like colon or hyphen) as the relation name.
    """
    for i, line in enumerate(text_lines):
        lower_line = line.lower()

        # Check if the line has a separator (colon, semicolon, em-dash, en-dash, or hyphen)
        sep_match = re.search(r'[:;—–-]', line)
        if sep_match:
            sep = sep_match.group(0)
            left, right = line.split(sep, 1)
            left_clean = left.strip().lower()

            # Skip if this is the voter's own name line
            if left_clean in ["name", "nane", "nmae", "neme", "nama", "vame", "wame", "mane"]:
                continue

            # Skip if this is the house number line
            if any(h in left_clean for h in ["house", "hause", "hous", "huse", "ho.us", "h0us", "touse", "louse", "nouse", "ouse"]):
                continue

            # Skip if this is the age / gender line
            if any(ag in left_clean for ag in ["age", "aqe", "gender", "sex"]):
                continue

            # Skip if it is an EPIC number or serial number
            if _EPIC_TOKEN_RE.match(left_clean) or left_clean.isdigit():
                continue

            # Classify the relationship type based on the label before the separator
            rel_type = "Other"
            if any(f in left_clean for f in ["father", "fath", "fater", "tather"]):
                rel_type = "Father"
            elif any(h in left_clean for h in ["husband", "husb", "husoand", "nusoand", "hushand", "husban"]):
                rel_type = "Husband"
            elif any(m in left_clean for m in ["mother", "moth", "moter", "nother"]):
                rel_type = "Mother"
            elif any(w in left_clean for w in ["wife", "wfe", "wiife"]):
                rel_type = "Wife"

            val = right.strip()

            # If value is empty, very short, or noise, search subsequent lines
            if not val or len(val) < 2 or _is_photo_noise(val):
                for j in range(i + 1, min(i + 3, len(text_lines))):
                    next_line = text_lines[j].strip()
                    next_lower = next_line.lower()

                    # Skip lines that are other field labels
                    if any(k in next_lower for k in ["house", "age", "gender", "sex", "photo", "number"]):
                        break

                    # Handle "Name : Shiva Naka" on the next line
                    if any(n in next_lower for n in ["name", "nane", "nmae"]) and ":" in next_line:
                        candidate = next_line.split(":", 1)[1].strip()
                        candidate = re.sub(r'^[\s:.-]+', '', candidate).strip()
                        if candidate and len(candidate) >= 2 and not _is_photo_noise(candidate):
                            val = candidate
                            break

                    # Handle plain name on next line (no "Name :" prefix)
                    if not any(n in next_lower for n in ["name", "nane", "nmae"]) and ":" not in next_line:
                        candidate = re.sub(r'^[\s:.-]+', '', next_line).strip()
                        if candidate and len(candidate) >= 2 and not _is_photo_noise(candidate):
                            val = candidate
                            break

            # Reject noise values
            if _is_photo_noise(val):
                val = ""

            return rel_type, val

    # Fallback to the keyword prefix-stripping matching if no separated line is found
    for i, line in enumerate(text_lines):
        lower_line = line.lower()

        rel_type = ""
        # Match typos for Father
        if any(f in lower_line for f in ["father", "fath", "fater", "tather"]):
            rel_type = "Father"
        # Match typos for Husband
        elif any(h in lower_line for h in ["husband", "husb", "husoand", "nusoand", "hushand", "husban"]):
            rel_type = "Husband"
        # Match typos for Mother
        elif any(m in lower_line for m in ["mother", "moth", "moter", "nother"]):
            rel_type = "Mother"
        # Match typos for Wife
        elif any(w in lower_line for w in ["wife", "wfe", "wiife"]):
            rel_type = "Wife"
        # Match typos for Other using word boundaries to avoid matching names containing substring "guru"
        elif any(re.search(rf'\b{o}\b', lower_line) for o in ["other", "othr", "gurdian", "guardian", "guru"]):
            rel_type = "Other"
        else:
            continue

        # Extract value using robust regex to strip relationship prefix and typos
        val = re.sub(
            r'^(?:father|fath|fater|tather|husband|husb|husoand|nusoand|hushand|husban|mother|moth|moter|nother|wife|wfe|wiife|other|othr|guardian|gurdian|guru)s?(?:\'s|s)?\s*(?:name|nane|nmae|neme|nama)?\s*[:.\-–\s]*',
            '',
            line,
            flags=re.IGNORECASE
        ).strip()

        # If value is empty, very short, or just noise, look at subsequent lines
        if not val or len(val) < 2 or _is_photo_noise(val):
            for j in range(i + 1, min(i + 3, len(text_lines))):
                next_line = text_lines[j].strip()
                next_lower = next_line.lower()

                # Skip lines that are other field labels
                if any(k in next_lower for k in ["house", "age", "gender", "sex", "photo", "number"]):
                    break

                # Handle "Name : Shiva Naka" on the next line
                if any(n in next_lower for n in ["name", "nane", "nmae"]) and ":" in next_line:
                    candidate = next_line.split(":", 1)[1].strip()
                    candidate = re.sub(r'^[\s:.-]+', '', candidate).strip()
                    if candidate and len(candidate) >= 2 and not _is_photo_noise(candidate):
                        val = candidate
                        break

                # Handle plain name on next line (no "Name :" prefix)
                if not any(n in next_lower for n in ["name", "nane", "nmae"]) and ":" not in next_line:
                    candidate = re.sub(r'^[\s:.-]+', '', next_line).strip()
                    if candidate and len(candidate) >= 2 and not _is_photo_noise(candidate):
                        val = candidate
                        break

        # Reject noise values
        if _is_photo_noise(val):
            val = ""

        return rel_type, val

    return "", ""


def is_valid_house_no_value(val: str) -> bool:
    """
    Checks if a candidate house number value is valid (not photo box noise, EPIC, or labels).
    """
    val_clean = val.strip().lower()
    if not val_clean:
        return False
    
    # Reject if it contains keywords related to photo placeholders or other fields
    keywords = [
        "photo", "available", "avalable", "availble", "avallab", "image", "picture",
        "name", "father", "husband", "mother", "wife", "relation", "age", "gender", "sex",
        "nmd", "hvq"  # standard EPIC prefixes
    ]
    if any(k in val_clean for k in keywords):
        return False
        
    # Reject single-character noise that is not a digit or standard placeholder
    if len(val_clean) == 1 and not val_clean.isdigit() and val_clean not in ["#", "-", "/"]:
        return False
        
    # Check if it's a full EPIC number
    if _EPIC_TOKEN_RE.match(val_clean):
        return False
        
    return True


def parse_house_no(text_lines: List[str], sl_no: str = "", epic_no: str = "") -> str:
    """
    Extracts house number, supporting typos and cleaning placeholder/null values.
    """
    # Expanded house labels to cover common typos
    house_labels = [
        "house", "hause", "hous", "huse", "ho.us", "h0us", "h.no", "h.o", "hse",
        "h no", "h. no", "h. o", "ho.no", "ho no", "house no", "house no.", "house number",
        "h no.", "h.no.", "h. o.", "h.o.", "ouse", "ouse no", "ouse no.", "ouse number",
        "touse", "touse no", "touse number", "louse", "louse no", "louse number",
        "nouse", "nouse no", "nouse number"
    ]
    
    for i, line in enumerate(text_lines):
        lower_line = line.lower()
        if any(h in lower_line for h in house_labels):
            # Extract by stripping prefix
            val = re.sub(
                r'^(?:[htln]?ouse|[htln]?ause|hous|huse|ho\.us|h0us|h\.no|h\.o|hse|h\s+no|ho\s+no|ho\.no)\s*(?:number|no|no\.)?\s*[:.\-–\s]*',
                '',
                line,
                flags=re.IGNORECASE
            ).strip()
            
            # If the inline value is not valid, or empty, check the next line
            if not val or not is_valid_house_no_value(val):
                # We can check next lines (up to 2 lines)
                checked_val = ""
                for j in range(i + 1, min(i + 3, len(text_lines))):
                    candidate = text_lines[j].strip()
                    if is_valid_house_no_value(candidate):
                        checked_val = candidate
                        break
                    # If we encounter another field's label on next line, don't keep searching
                    candidate_lower = candidate.lower()
                    if any(k in candidate_lower for k in ["age", "gender", "sex", "name", "relation"]):
                        break
                val = checked_val
            
            val = val.strip()
            
            # Clean placeholder empty/null values, mapping them to "#"
            val_lower = val.lower()
            if not val or val_lower in ["#", "-", "--", "nil", "null", "none", "empty", "", "nil.", "none.", "no", "no."]:
                val = "#"
            else:
                return val
                
    # --- Fallback: Verify Twice ---
    # Look for the age/gender line, then look at the lines preceding it, skipping noise.
    for i, line in enumerate(text_lines):
        lower_line = line.lower()
        # Detect Age/Gender line
        is_age_gender = (
            _AGE_KEYWORDS.search(lower_line) or 
            _GENDER_KEYWORDS.search(lower_line) or
            any(g in lower_line for g in ["female", "male", "transgender", "third", "femate", "femafe", "femaie", "maie", "nale", "mafe", "mele"])
        )
        if is_age_gender:
            # Check up to 3 lines above the Age/Gender line
            for offset in range(1, 4):
                if i - offset < 0:
                    break
                candidate = text_lines[i - offset].strip()
                candidate_lower = candidate.lower()
                
                # If it's a known noise line (like "photo", "available", etc.), skip and look further up
                if any(noise in candidate_lower for noise in ["photo", "available", "avalable", "availble", "avallab", "image", "picture"]):
                    continue
                    
                # 1. Skip if it looks like a name or relation line
                skip_keywords = [
                    "name", "nane", "nmae", "neme", "nama",
                    "father", "fath", "fater", "tather",
                    "husband", "husb", "husoand", "nusoand", "hushand", "husban",
                    "mother", "moth", "moter", "nother",
                    "wife", "wfe", "wiife",
                    "other", "othr", "gurdian", "guardian", "guru", "relation",
                    "age", "gender", "sex", "years", "yeares", "yeas"
                ]
                if any(k in candidate_lower for k in skip_keywords):
                    # If we hit a name/relation line, stop looking further
                    break
                    
                # 2. Skip if it is an EPIC number
                if _EPIC_TOKEN_RE.match(candidate_lower) or any(prefix in candidate_lower for prefix in ["nmd", "hvq"]):
                    continue
                    
                # 3. Skip if it matches the current card's sl_no or epic_no
                if sl_no and candidate_lower == sl_no.strip().lower():
                    continue
                if epic_no and candidate_lower == epic_no.strip().lower():
                    continue
                    
                # Strip potential house no typos in candidate line
                cleaned_candidate = re.sub(
                    r'^(?:[htln]?ouse|[htln]?ause|hous|huse|ho\.us|h0us|h\.no|h\.o|hse|h\s+no|ho\s+no|ho\.no)\s*(?:number|no|no\.)?\s*[:.\-–\s]*',
                    '',
                    candidate,
                    flags=re.IGNORECASE
                ).strip()
                
                if is_valid_house_no_value(cleaned_candidate):
                    val_lower = cleaned_candidate.lower()
                    if val_lower in ["#", "-", "--", "nil", "null", "none", "empty", "", "nil.", "none.", "no", "no."]:
                        return "#"
                    return cleaned_candidate

    return "#"


# Robust age parsing matching the label + value combination to bypass boundary constraints (e.g. Age38)
_AGE_PATTERN = re.compile(
    r'\b(?:age|aqe|ag|a9e|aoe|a8e|a6e|aee|asge|ag[ée]|years?|ae)[.\s:.\-–]*(\d{1,3})',
    re.IGNORECASE
)

# Robust gender pattern matching label + value (e.g. GenderFemale)
_GENDER_PATTERN = re.compile(
    r'\b(?:gender|sex|qender|gend|gen\s*der|gander|sen)[.\s:.\-–]*([a-zA-Z]+)',
    re.IGNORECASE
)

# standalone gender matching to search anywhere in card for typos
_STANDALONE_GENDER_PATTERN = re.compile(
    r'\b(female|male|transgender|third|femate|femafe|femaie|maie|nale|mafe|m\s*ale|mal\s*e|femal|fe\s*male|fernale|mele|femäle|mäle)\b',
    re.IGNORECASE
)


def parse_age_gender(text_lines: List[str]) -> Tuple[str, str]:
    """
    Extracts age and gender. Handles combined lines and split OCR.
    Accounts for common OCR misreads (Maie→Male, femate→Female, etc.).
    """
    age = ""
    gender = ""
    combined = " ".join(text_lines)

    # 1. Age extraction
    age_match = _AGE_PATTERN.search(combined)
    if age_match:
        age = age_match.group(1)
        
    if not age:
        # Line-by-line fallback
        for i, line in enumerate(text_lines):
            if any(k in line.lower() for k in ["age", "aqe", "a9e", "aoe", "a8e", "a6e", "aee", "asge", "years", "ae"]):
                dig = re.search(r'(\d{1,3})', line)
                if dig:
                    age = dig.group(1)
                    break
                if i + 1 < len(text_lines):
                    dig_next = re.search(r'^\s*(\d{1,3})\s*$', text_lines[i + 1])
                    if dig_next:
                        age = dig_next.group(1)
                        break

    # 2. Gender extraction
    gender_match = _GENDER_PATTERN.search(combined)
    if gender_match:
        gender = gender_match.group(1)
        
    if not gender:
        gender_fallback = _STANDALONE_GENDER_PATTERN.search(combined)
        if gender_fallback:
            gender = gender_fallback.group(1)

    return age, gender



def parse_card_text(text_lines: List[str]) -> Dict[str, str]:
    """
    Parses a single voter card text lines into structured fields.
    """
    is_deleted = any("delete" in line.lower() for line in text_lines)

    sl_no = parse_sl_no(text_lines)
    epic_no = parse_epic_no(text_lines)
    name = parse_name(text_lines)
    rel_type, rel_name = parse_relation(text_lines)
    house_no = parse_house_no(text_lines, sl_no, epic_no)
    age, gender = parse_age_gender(text_lines)

    if is_deleted and name:
        name = f"[DELETED] {name}"

    return {
        "sl_no": sl_no,
        "epic_no": epic_no,
        "name": name,
        "relation_type": rel_type,
        "relation_name": rel_name,
        "house_no": house_no,
        "age": age,
        "gender": gender
    }
