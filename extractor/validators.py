import re
from typing import Dict, Any, List, Tuple

# EPIC pattern standard match: e.g. NMD3001203 or standard 3-letters followed by 7-digits
EPIC_PATTERN = re.compile(r'^[A-Z]{3}\d{7}$', re.IGNORECASE)

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
    Validates that the age is a numeric integer.
    Returns: (is_valid, warning_message)
    """
    age_str = str(age_val).strip()
    if not age_str:
        return False, "Age is missing."
    if not age_str.isdigit():
        return False, f"Age '{age_str}' is non-numeric."
    val = int(age_str)
    if val < 18 or val > 125:
        return True, f"Age '{val}' is outside typical limit (18-125)."
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

    # 4. Standardize Relation Type
    rel_type = str(cleaned.get("relation_type", "")).strip().capitalize()
    if rel_type not in ["Father", "Husband", "Mother", "Wife"]:
        if rel_type:
            warnings.append(f"Unknown relation type '{rel_type}'.")
    cleaned["relation_type"] = rel_type

    # 5. Clean Relation Name
    rel_name = str(cleaned.get("relation_name", "")).strip()
    cleaned["relation_name"] = rel_name
    if name and not rel_name:
        warnings.append("Relative name is missing.")

    # 6. Validate House Number
    house_no = str(cleaned.get("house_no", "")).strip()
    cleaned["house_no"] = house_no
    if not house_no:
        warnings.append("House number is missing.")

    # 7. Validate Age
    age = cleaned.get("age", "")
    is_age_ok, age_warn = validate_age(age)
    if age_warn:
        warnings.append(age_warn)
    if is_age_ok and str(age).strip().isdigit():
        cleaned["age"] = int(str(age).strip())
    else:
        cleaned["age"] = age

    # 8. Standardize Gender
    gender = str(cleaned.get("gender", "")).strip().lower()
    if "female" in gender or gender == "f":
        cleaned["gender"] = "Female"
    elif "male" in gender or gender == "m":
        cleaned["gender"] = "Male"
    elif "third" in gender or "trans" in gender or "other" in gender:
        cleaned["gender"] = "Third Gender"
    else:
        cleaned["gender"] = gender.capitalize() if gender else ""
        if gender:
            warnings.append(f"Unusual gender value '{gender}'.")

    return warnings, cleaned

def is_record_creatable(record: Dict[str, Any]) -> bool:
    """
    Checks if a record is valid for creation (contains both sl_no and epic_no).
    """
    sl_str = str(record.get("sl_no", "")).strip()
    epic_str = str(record.get("epic_no", "")).strip()
    
    # We require a non-empty serial number (digits only) and a non-empty EPIC number
    if not sl_str.isdigit():
        return False
    if not epic_str:
        return False
    return True
