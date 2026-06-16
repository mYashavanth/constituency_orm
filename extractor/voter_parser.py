import re
from typing import List, Dict, Tuple, Any
from extractor.logger import logger

# Matches an EPIC-style token: 3 letters + 6-7 digits (9 or 10 chars total)
_EPIC_TOKEN_RE = re.compile(r'^[A-Z]{2,3}[0-9]{6,7}$', re.IGNORECASE)

def parse_sl_no(text_lines: List[str]) -> str:
    """
    Extracts voter Serial Number. It is typically a standalone integer.
    Scans all lines (card order can vary) and skips EPIC-like tokens.
    """
    for line in text_lines:
        stripped = line.strip()
        # Skip lines that look like an EPIC number
        if _EPIC_TOKEN_RE.match(stripped):
            continue
        cleaned = re.sub(r'[^\d]', '', stripped)
        if cleaned and len(cleaned) <= 4:
            return cleaned
    return ""

def parse_epic_no(text_lines: List[str]) -> str:
    """
    Extracts EPIC Number.
    Karnataka EPICs are typically [A-Z]{3}[0-9]{6,7} (9 or 10 chars).
    e.g. NMD100508 (9-char) or NMD3001203 (10-char) or HVQ132750 (9-char)
    """
    combined = " ".join(text_lines)

    # 1. Primary: 2-3 capital letters followed by 6-7 digits (covers both 9 and 10-char forms)
    primary = re.search(r'\b([A-Z]{2,3}\d{6,7})\b', combined, re.IGNORECASE)
    if primary:
        return primary.group(1).upper()

    # 2. Fallback: any 9-10 char mixed alphanumeric token with letters at start
    flexible = re.search(r'\b([A-Z]{2,3}[A-Z0-9]{6,7})\b', combined, re.IGNORECASE)
    if flexible:
        val = flexible.group(1).upper()
        if any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            return val

    return ""

def parse_name(text_lines: List[str]) -> str:
    """
    Extracts voter name. Looks for lines containing "Name" and filters out relation names.
    """
    for line in text_lines:
        lower_line = line.lower()
        if "name" in lower_line and not any(k in lower_line for k in ["father", "husband", "mother", "wife", "relation"]):
            parts = line.split(":", 1)
            name_val = parts[1].strip() if len(parts) > 1 else line.replace("Name", "").replace("Name:", "").strip()
            name_val = re.sub(r'^[\s:.-]+', '', name_val)
            return name_val.strip()
            
    # Fallback to the first long alphabetical line that isn't a keyword
    for line in text_lines:
        lower_line = line.lower()
        if not any(k in lower_line for k in ["name", "father", "husband", "mother", "wife", "house", "number", "no.", "age", "gender", "sex", "photo", "available", "deleted"]):
            cleaned_line = line.strip()
            if len(cleaned_line) > 3 and not re.match(r'^[A-Z]{3}\d{7}$', cleaned_line, re.IGNORECASE) and not cleaned_line.isdigit():
                return cleaned_line
                
    return ""

def parse_relation(text_lines: List[str]) -> Tuple[str, str]:
    """
    Extracts relationship type and relative name.
    """
    for line in text_lines:
        lower_line = line.lower()
        if "father" in lower_line:
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else line.replace("Father's Name", "").replace("Father Name", "").replace("FatherName", "").strip()
            val = re.sub(r'^[\s:.-]+', '', val)
            return "Father", val.strip()
        elif "husband" in lower_line:
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else line.replace("Husband's Name", "").replace("Husband Name", "").replace("HusbandName", "").strip()
            val = re.sub(r'^[\s:.-]+', '', val)
            return "Husband", val.strip()
        elif "mother" in lower_line:
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else line.replace("Mother's Name", "").replace("Mother Name", "").replace("MotherName", "").strip()
            val = re.sub(r'^[\s:.-]+', '', val)
            return "Mother", val.strip()
        elif "wife" in lower_line:
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else line.replace("Wife's Name", "").replace("Wife Name", "").replace("WifeName", "").strip()
            val = re.sub(r'^[\s:.-]+', '', val)
            return "Wife", val.strip()
            
    return "", ""

def parse_house_no(text_lines: List[str]) -> str:
    """
    Extracts house number.
    """
    for line in text_lines:
        lower_line = line.lower()
        if "house" in lower_line or "house number" in lower_line:
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else line.replace("House Number", "").replace("House No", "").replace("HouseNo", "").replace("House No.", "").strip()
            val = re.sub(r'^[\s:.-]+', '', val)
            return val.strip()
    return ""

def parse_age_gender(text_lines: List[str]) -> Tuple[str, str]:
    """
    Extracts age and gender. Often combined on one line.
    """
    age = ""
    gender = ""
    combined = " ".join(text_lines)
    
    age_match = re.search(r'age\s*:\s*(\d+)', combined, re.IGNORECASE)
    if age_match:
        age = age_match.group(1)
    else:
        age_match = re.search(r'\bage\s+(\d+)\b', combined, re.IGNORECASE)
        if age_match:
            age = age_match.group(1)
            
    gender_match = re.search(r'(?:gender|sex)\s*:\s*(\w+)', combined, re.IGNORECASE)
    if gender_match:
        gender = gender_match.group(1)
    else:
        gender_match = re.search(r'\b(?:gender|sex)\s+(\w+)\b', combined, re.IGNORECASE)
        if gender_match:
            gender = gender_match.group(1)
            
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
    house_no = parse_house_no(text_lines)
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
