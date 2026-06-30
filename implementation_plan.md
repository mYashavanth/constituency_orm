# Implementation Plan - Extraction Accuracy & Validation Enhancements

This plan outlines changes to improve extraction accuracy, handle "DELETED" voter stamps, correct identical name/relation name errors, and clean OCR name label typos (e.g., `lame`, `jame`, `ame`).

## User Review Required

> [!NOTE]
> **1. Handling of "DELETED" Citizens:**
> When a voter is marked as deleted on the roll, we will:
> - Flag them with a warning in the "Validation Warnings & Errors" tab of the application UI.
> - Leave their name unmodified in the Excel export as requested.
> 
> **2. Duplicate Name & Relation Name Flagging:**
> If the parser extracts the same name for both the voter and their relative, we will:
> - Log a warning in the validation tab: `"Voter name and relation name are identical."`
> - Clean/prevent this by correctly identifying and ignoring name-prefix OCR typos (like `jame:`, `lame:`, `ame:`) when parsing relationship lines.

---

## Proposed Changes

### Extractor Core Logic

#### [MODIFY] [voter_parser.py](file:///Users/yash/Documents/projects/constituency_orm/extractor/voter_parser.py)
- Adds a robust `_NAME_LABEL_RE` regular expression to match and clean standard OCR name typos (`lame`, `jame`, `ame`, etc.).
- Adds a robust `_DELETED_RE` regex to identify deleted stamps on voter cards.
- Updates `parse_name` and `parse_relation` to use `_NAME_LABEL_RE` for correct name extraction and relative line skipping.
- Modifies `parse_card_text` to check for deleted stamps and populate the `is_deleted` key.

#### [MODIFY] [validators.py](file:///Users/yash/Documents/projects/constituency_orm/extractor/validators.py)
- Updates `validate_voter_record` to check for the `is_deleted` flag and log a validation warning.
- Updates `validate_voter_record` to verify if the voter name and relation name are identical, appending a warning to alert the user.

---

### File Edits

#### [MODIFY] `voter_parser.py`
*Add regex and modify parsing logic:*
```python
# Matches "Name" and common OCR typos like lame, jame, ame, mane, nane, nmae, etc.
_NAME_LABEL_RE = re.compile(
    r'\b(?:[nljawvmrtdhgs]?ame|[nljawvmrtdhgs]?ane|nmae|neme|nama)\b',
    re.IGNORECASE
)

# Matches "DELETED" stamp and its common OCR misread variants
_DELETED_RE = re.compile(
    r'\b(?:delet|deiet|de-let|del-et|d[.\s]*e[.\s]*l[.\s]*e[.\s]*t[.\s]*e[.\s]*d)\w*\b',
    re.IGNORECASE
)
```

#### [MODIFY] `validators.py`
*Add duplicate name/relation and deleted checking in `validate_voter_record`:*
```python
    # 3. Validate name
    name = str(cleaned.get("name", "")).strip()
    cleaned["name"] = name
    if not name:
        warnings.append("Voter name is missing.")

    if cleaned.get("is_deleted"):
        warnings.append("Voter is marked as DELETED on the roll.")

    # 5. Clean Relation Name
    rel_name = str(cleaned.get("relation_name", "")).strip()
    cleaned["relation_name"] = rel_name
    if not rel_name:
        warnings.append("Relative name is missing.")
    elif name and rel_name and name.lower() == rel_name.lower():
        warnings.append("Voter name and relation name are identical.")
```

---

## Verification Plan

### Automated Tests
- Run `python extractor/test_extraction.py` to ensure the E2E extraction works and completes without regressions.

### Manual Verification
1. Load a PDF containing deleted cards (e.g. Card 481 in `2.pdf`) into the UI.
2. Verify that the "Validation Warnings & Errors" tab lists the warning: `"Voter is marked as DELETED on the roll."`
3. Verify that the voter's name in Excel does NOT have `[DELETED]` prefix, keeping the raw name intact.
4. Verify that the "Validation Warnings & Errors" tab lists the warnings for identical voter and relation names.
