"""
validator.py

Generic validator for ANSI X12 transactions.
Returns AK3 errors that can be passed directly to build_997().
"""

from datetime import datetime


def is_required(value):
    """Checks if a required field has a value."""
    return value not in (None, "", [], {})


def is_valid_date(value):
    """Validate YYYYMMDD format."""
    if not value:
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def is_numeric(value):
    """Checks whether a value contains only digits."""
    return value is not None and str(value).isdigit()


def validate(parsed, required_rules, field_rules=None, stop_rules=None):
    """
    Generic validator.

    required_rules:
        (field, segment, position)

    field_rules:
        (field, validator, segment, position)

    stop_rules:
        (field, validator, segment)
    """

    errors = []

    # Validate required top-level fields
    for field, segment, position in required_rules:
        if not is_required(parsed.get(field)):
            errors.append({
                "segment_id": segment,
                "position": position,
                "code": "8"
            })

    # Validate top-level field values
    for field, validator, segment, position in field_rules or []:
        value = parsed.get(field)
        if is_required(value) and not validator(value):
            errors.append({
                "segment_id": segment,
                "position": position,
                "code": "8"
            })

    # Validate repeating stop data
    for stop in parsed.get("stops", []):
        positions = stop.get("_positions", {})
        stop_no = stop.get("stop_number", "")
        for field, validator, segment in stop_rules or []:
            value = stop.get(field)
            if not is_required(value) or not validator(value):
                # Use the segment's real position in the transaction if we
                # recorded one while parsing; fall back to the stop number
                # only if that segment never appeared at all (so there's
                # nothing more precise to point at).
                real_position = positions.get(segment, stop_no)
                errors.append({
                    "segment_id": segment,
                    "position": real_position,
                    "code": "8"
                })

    return errors


REQUIRED_204 = [
    ("shipment_id", "L11", 4),
    ("payment_terms", "B2", 2),
    ("tender_purpose", "B2A", 3),
    ("equipment_type", "N7", 6),
    ("stops", "S5", 8),
]

FIELD_RULES_204 = [
    ("total_weight", is_numeric, "L3", 20),
    ("total_charge", is_numeric, "L3", 21),
]

STOP_RULES_204 = [
    ("appointment_date", is_valid_date, "G62"),
    ("facility_name", is_required, "N1"),
    ("city", is_required, "N4"),
    ("state", is_required, "N4"),
    ("zip", is_required, "N4"),
]


def validate_204(parsed):
    """Validate a parsed 204 transaction."""
    return validate(
        parsed,
        REQUIRED_204,
        FIELD_RULES_204,
        STOP_RULES_204
    )
