"""
validate.py — checks envelope and transaction rules for X12 204s.
Never raises — always returns a list of errors (empty list = valid).
"""

from datetime import datetime


def find_seg(segments, seg_id):
    return next((s for s in segments if s[0] == seg_id), None)


def validate_envelope(segments):
    """Checks ISA13==IEA02 and GS06==GE02 for a full interchange."""
    errors = []
    isa, iea = find_seg(segments, "ISA"), find_seg(segments, "IEA")
    gs, ge = find_seg(segments, "GS"), find_seg(segments, "GE")

    if not isa:
        errors.append({"code": "MISSING_ISA", "message": "No ISA segment found."})
    if not iea:
        errors.append({"code": "MISSING_IEA", "message": "No IEA segment found."})
    if isa and iea and isa[13] != iea[2]:
        errors.append({
            "code": "ISA_IEA_CONTROL_MISMATCH",
            "message": f"ISA13='{isa[13]}' does not match IEA02='{iea[2]}'."
        })

    if not gs:
        errors.append({"code": "MISSING_GS", "message": "No GS segment found."})
    if not ge:
        errors.append({"code": "MISSING_GE", "message": "No GE segment found."})
    if gs and ge and gs[6] != ge[2]:
        errors.append({
            "code": "GS_GE_CONTROL_MISMATCH",
            "message": f"GS06='{gs[6]}' does not match GE02='{ge[2]}'."
        })

    return errors


def validate_transaction(txn_segments):
    """Checks ST02==SE02 and SE01==actual segment count for one transaction."""
    errors = []
    st = txn_segments[0] if txn_segments[0][0] == "ST" else None
    se = txn_segments[-1] if txn_segments[-1][0] == "SE" else None

    if not st:
        errors.append({"code": "MISSING_ST", "message": "Transaction has no ST segment."})
    if not se:
        errors.append({"code": "MISSING_SE", "message": "Transaction has no SE segment."})
    if not (st and se):
        return errors

    if st[2] != se[2]:
        errors.append({
            "code": "ST_SE_CONTROL_MISMATCH",
            "message": f"ST02='{st[2]}' does not match SE02='{se[2]}'."
        })

    actual_count = len(txn_segments)
    try:
        declared_count = int(se[1])
    except (ValueError, IndexError):
        declared_count = None

    if declared_count != actual_count:
        errors.append({
            "code": "SE_COUNT_MISMATCH",
            "message": (f"SE01 declares {se[1]} segments but transaction "
                        f"actually has {actual_count} (ST through SE inclusive).")
        })

    return errors


def build_segment_set_from_reference(reference_path, exclude_envelope=True):
    """
    Reads a known-good reference file and returns the set of segment
    IDs it actually uses. Point this at a different file to validate
    a different partner or transaction type — no code changes needed.
    """
    from tokenizer import tokenize

    with open(reference_path) as f:
        text = f.read()
    _, segments = tokenize(text)

    envelope_ids = {"ISA", "GS", "GE", "IEA"} if exclude_envelope else set()
    return {seg[0] for seg in segments if seg[0] not in envelope_ids}


def _find_reference_file(data_dir):
    """
    Picks a reference file to derive the default segment set from.
    Checks, in order:
      1. The EDI_REFERENCE_FILE environment variable, if set.
      2. Any file in data_dir whose name contains "clean" (case-insensitive).
      3. The first .edi file found in data_dir, alphabetically.
    Returns None if data_dir doesn't exist or has no .edi files.
    """
    import os

    env_path = os.environ.get("EDI_REFERENCE_FILE")
    if env_path and os.path.isfile(env_path):
        return env_path

    if not os.path.isdir(data_dir):
        return None

    edi_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".edi"))
    if not edi_files:
        return None

    clean_matches = [f for f in edi_files if "clean" in f.lower()]
    chosen = clean_matches[0] if clean_matches else edi_files[0]
    return os.path.join(data_dir, chosen)


def _default_segment_set():
    """
    Derives the default segment set from a reference file (see
    _find_reference_file for how it's chosen). Returns None if no
    reference file can be found — that's a deliberate signal meaning
    "we have no basis to say what's valid," not a guess.
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(here, "..", "data")
    reference_path = _find_reference_file(data_dir)
    if reference_path is None:
        return None
    try:
        return build_segment_set_from_reference(reference_path)
    except (FileNotFoundError, ValueError, OSError):
        return None


DEFAULT_204_SEGMENTS = _default_segment_set()


def validate_segment_ids(txn_segments, known_segments=None):
    """
    Flags any segment ID not in known_segments (e.g. a stray ZZZ).
    Falls back to DEFAULT_204_SEGMENTS if known_segments isn't given.
    If no default is available either, skips this check (returns []).
    """
    allowed = known_segments if known_segments is not None else DEFAULT_204_SEGMENTS
    if allowed is None:
        return []

    errors = []
    for position, seg in enumerate(txn_segments, start=1):
        seg_id = seg[0]
        if seg_id not in allowed:
            errors.append({
                "code": "UNRECOGNIZED_SEGMENT",
                "segment_id": seg_id,
                "position": position,
                "message": (f"Segment '{seg_id}' at position {position} is not "
                            f"a recognized segment for this transaction type "
                            f"and cannot be processed.")
            })
    return errors


def validate_dates(txn_segments, date_format="%Y%m%d"):
    """Checks every G62 date is a real calendar date (catches e.g. Feb 31st)."""
    errors = []
    for position, seg in enumerate(txn_segments, start=1):
        if seg[0] != "G62":
            continue
        date_str = seg[2] if len(seg) > 2 else None
        if not date_str:
            continue
        try:
            datetime.strptime(date_str, date_format)
        except ValueError:
            errors.append({
                "code": "INVALID_DATE",
                "segment_id": "G62",
                "position": position,
                "message": (f"G62 at position {position} has date '{date_str}', "
                            f"which is not a valid calendar date.")
            })
    return errors


def validate_all(txn_segments, known_segments=None, date_format="%Y%m%d"):
    """Runs every transaction-level check and returns the combined error list."""
    errors = []
    errors += validate_transaction(txn_segments)
    errors += validate_segment_ids(txn_segments, known_segments)
    errors += validate_dates(txn_segments, date_format)
    return errors

def to_ak3_errors(errors, txn_segments):
    """
    Ensures every error dict has segment_id/position, so the combined
    error list from validate.py + validator.py can be passed straight
    to build_997()'s ak3_errors without a KeyError.

    Errors that already have both (e.g. UNRECOGNIZED_SEGMENT, INVALID_DATE,
    and anything from validator.py) pass through unchanged. Errors that
    don't (e.g. SE_COUNT_MISMATCH, which is about the whole transaction,
    not one segment) get pointed at the SE segment — the last segment in
    the transaction — since that's where a count mismatch is actually
    detected, and "code" defaults to a generic placeholder.
    """
    result = []
    for err in errors:
        if "segment_id" in err and "position" in err:
            result.append(err)
        else:
            result.append({
                "segment_id": "SE",
                "position": len(txn_segments),
                "code": err.get("code", "UNKNOWN"),
            })
    return result


if __name__ == "__main__":
    import sys
    import os
    import json

    sys.path.insert(0, os.path.dirname(__file__))
    from tokenizer import tokenize
    from parser_204 import find_transactions

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")

    input_filename = sys.argv[1] if len(sys.argv) > 1 else "sample_204_clean.edi"
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )
    text = open(input_path).read()

    delims, segments = tokenize(text)
    print("Envelope errors:", json.dumps(validate_envelope(segments), indent=2))

    for i, txn in enumerate(find_transactions(segments)):
        errs = validate_all(txn)
        print(f"Transaction {i + 1} errors:", json.dumps(errs, indent=2))
