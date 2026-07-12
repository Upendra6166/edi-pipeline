"""
validate.py — checks envelope and transaction control-number/count rules.
Never raises — always returns a list of errors (empty list = valid).
"""


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


if __name__ == "__main__":
    import sys, os, json
    sys.path.insert(0, os.path.dirname(__file__))
    from tokenizer import tokenize
    from parser_204 import find_transactions

    path = sys.argv[1] if len(sys.argv) > 1 else "../data/sample_204_clean.edi"
    text = open(path).read()

    delims, segments = tokenize(text)
    print("Envelope errors:", json.dumps(validate_envelope(segments), indent=2))

    for i, txn in enumerate(find_transactions(segments)):
        errs = validate_transaction(txn)
        print(f"Transaction {i + 1} errors:", json.dumps(errs, indent=2))
