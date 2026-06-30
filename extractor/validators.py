import re
from typing import Dict, Any, List, Tuple

# EPIC pattern standard match: e.g. NMD3001203 or standard 3-letters followed by 7-digits
EPIC_PATTERN = re.compile(r'^[A-Z]{3}\d{7}$', re.IGNORECASE)
# Also allow 2-letter prefix + 7 digits (some states use 2-letter prefix)
EPIC_PATTERN_LOOSE = re.compile(r'^[A-Z]{2,3}\d{6,7}$', re.IGNORECASE)

# Known OCR typos for gender values
_OCR_MALE_VARIANTS = {"maie", "nale", "mafe", "m ale", "mal e", "mal", "ma le", "mäle", "mele"}
_OCR_FEMALE_VARIANTS = {"femate", "femafe", "femaie", "f emale", "femal", "fe male", "fernale", "femäle"}

def validate_epic(epic_no: str) -> Tuple[bool, str]:
    """
    Validates the EPIC number format.
    Returns: (is_valid, warning_message)
    """
    epic = str(epic_no).strip().upper()
    if not epic:
        return False, "EPIC number is missing."
    if not EPIC_PATTERN.match(epic):
        return False, f"EPIC '{epic}' does not match standard format [A-Z]{{3}}[0-9]{{7}}."
    return True, ""

def validate_age(age_val: Any) -> Tuple[bool, str]:
    """
    Validates that the age is a numeric integer between 18 and 125.
    Returns: (is_valid, warning_message)
    """
    age_str = str(age_val).strip()
    if not age_str:
        return False, "Age is missing."
    if not age_str.isdigit():
        return False, f"Age '{age_str}' is non-numeric."
    val = int(age_str)
    if val < 18 or val > 125:
        return False, f"Age '{val}' is outside typical limit (18-125)."
    return True, ""

def validate_voter_record(record: Dict[str, Any], expected_sl_no: int = None) -> Tuple[List[str], Dict[str, Any]]:
    """
    Validates and standardizes a voter record, returning warnings and the cleaned record.
    """
    warnings = []
    cleaned = record.copy()

    # 1. Clean Serial Number (sl_no)
    sl_str = str(cleaned.get("sl_no", "")).strip()
    if sl_str.isdigit():
        sl_val = int(sl_str)
        cleaned["sl_no"] = sl_val
        if expected_sl_no is not None and sl_val != expected_sl_no:
            warnings.append(f"Serial number '{sl_val}' is out of sequence (expected {expected_sl_no}).")
    else:
        # Non-numeric serial is flagged
        warnings.append(f"Serial number '{sl_str}' is invalid/non-numeric.")
        cleaned["sl_no"] = sl_str

    # 2. Clean EPIC Number
    epic = str(cleaned.get("epic_no", "")).strip().upper()
    cleaned["epic_no"] = epic
    is_epic_valid, epic_warn = validate_epic(epic)
    if epic_warn:
        warnings.append(epic_warn)

    # 3. Validate name
    name = str(cleaned.get("name", "")).strip()
    cleaned["name"] = name
    if not name:
        warnings.append("Voter name is missing.")

    if cleaned.get("is_deleted"):
        warnings.append("Voter is marked as DELETED on the roll.")

    # 4. Standardize Relation Type
    rel_type = str(cleaned.get("relation_type", "")).strip().capitalize()
    if not rel_type:
        warnings.append("Relation type is missing.")
    elif rel_type not in ["Father", "Husband", "Mother", "Wife", "Other", "Others"]:
        warnings.append(f"Unknown relation type '{rel_type}'.")
    cleaned["relation_type"] = rel_type

    # 5. Clean Relation Name
    rel_name = str(cleaned.get("relation_name", "")).strip()
    cleaned["relation_name"] = rel_name
    if not rel_name:
        warnings.append("Relative name is missing.")
    elif name and rel_name and name.lower() == rel_name.lower():
        warnings.append("Voter name and relation name are identical.")

    # 6. Validate House Number
    house_no = str(cleaned.get("house_no", "")).strip()
    if not house_no or house_no.lower() in ["#", "-", "--", "nil", "null", "none", "empty", "nil.", "none.", "no", "no."]:
        house_no = "#"
        warnings.append("House number is missing.")
    cleaned["house_no"] = house_no

    # 7. Validate Age
    age = cleaned.get("age", "")
    is_age_ok, age_warn = validate_age(age)
    if age_warn:
        warnings.append(age_warn)
    if is_age_ok and str(age).strip().isdigit():
        cleaned["age"] = int(str(age).strip())
    else:
        cleaned["age"] = age

    # 8. Standardize Gender — handle OCR typos
    gender_raw = str(cleaned.get("gender", "")).strip()
    if not gender_raw:
        warnings.append("Gender is missing.")
    gender = gender_raw.lower()
    if "female" in gender or gender == "f" or gender in _OCR_FEMALE_VARIANTS:
        cleaned["gender"] = "Female"
    elif "male" in gender or gender == "m" or gender in _OCR_MALE_VARIANTS:
        cleaned["gender"] = "Male"
    elif "third" in gender or "trans" in gender or "other" in gender:
        cleaned["gender"] = "Third Gender"
    else:
        cleaned["gender"] = gender_raw.capitalize() if gender_raw else ""
        if gender_raw:
            warnings.append(f"Unusual gender value '{gender_raw}'.")

    return warnings, cleaned

def is_record_creatable(record: Dict[str, Any]) -> bool:
    """
    Checks if a record has the minimum required fields to be saved.
    We require a non-empty EPIC number and a name with at least one alphabetic character.
    Serial number may be 0 (will be reconstructed sequentially by the pipeline from expected_sl_no).
    """
    sl_val = record.get("sl_no", "")
    epic_str = str(record.get("epic_no", "")).strip()

    # Must have a valid EPIC number (allowing for loose length check to prevent OCR drops)
    if not epic_str or not (5 <= len(epic_str) <= 15):
        return False

    # Must have a name containing at least one alphabetic character
    name_str = str(record.get("name", "")).strip()
    if not name_str or not any(c.isalpha() for c in name_str):
        return False

    # sl_no must be either a positive integer or the string of one
    # sl_no == 0 is allowed (will be reconstructed by pipeline)
    sl_str = str(sl_val).strip()
    if sl_str.isdigit():
        return True  # includes 0, pipeline will fix it
    return False
