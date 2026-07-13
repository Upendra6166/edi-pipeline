"""
error_log.py — turns validate.py's error dicts into a plain-English log
a non-technical support agent can read and act on, and into AK3/AK4
segment-level detail for a rejecting 997.
"""

FRIENDLY_TEMPLATES = {
    "SE_COUNT_MISMATCH": (
        "This shipment's file looks incomplete or corrupted — it claims "
        "to have a different number of sections than it actually contains. "
        "Ask the sender to re-transmit this load tender."
    ),
    "UNRECOGNIZED_SEGMENT": (
        "This shipment's file contains an unexpected data block "
        "(labeled '{segment_id}') that isn't part of a normal load tender. "
        "This usually means the sender's system sent test or extra data "
        "by mistake — check with them before processing this load."
    ),
    "INVALID_DATE": (
        "One of the appointment dates on this shipment isn't a real "
        "calendar date. Contact the sender to confirm the correct "
        "pickup or delivery date before scheduling."
    ),
    "ISA_IEA_CONTROL_MISMATCH": (
        "The file's outer envelope numbers don't match up, which usually "
        "means the file was cut off or corrupted in transit. Ask the "
        "sender to resend the complete file."
    ),
    "GS_GE_CONTROL_MISMATCH": (
        "The file's group-level numbers don't match up, which usually "
        "means the file was cut off or corrupted in transit. Ask the "
        "sender to resend the complete file."
    ),
    "ST_SE_CONTROL_MISMATCH": (
        "This shipment's transaction numbers don't match up, which "
        "usually means the file was cut off or corrupted in transit."
    ),
}


def build_error_log(errors, shipment_id=None, po_number=None):
    """Returns a list of plain-English strings, one per error."""
    header = "Shipment "
    if shipment_id:
        header += f"{shipment_id} "
    if po_number:
        header += f"(PO {po_number}) "
    header = header.strip() or "This shipment"

    lines = []
    for err in errors:
        template = FRIENDLY_TEMPLATES.get(
            err["code"], err.get("message", "An unspecified error occurred.")
        )
        friendly = template.format(**err) if "{" in template else template
        lines.append(f"{header}: {friendly}")
    return lines


def write_error_log(errors, path, shipment_id=None, po_number=None):
    """Writes the plain-English log to a text file, one error per line."""
    lines = build_error_log(errors, shipment_id, po_number)
    with open(path, "w") as f:
        if not lines:
            f.write("No errors detected.\n")
        else:
            f.write("\n".join(lines) + "\n")
    return lines


def to_ak3_ak4(errors):
    """Converts positioned errors into AK3 segment-level entries."""
    ak3_list = []
    for err in errors:
        if "position" in err and "segment_id" in err:
            ak3_list.append({
                "segment_id": err["segment_id"],
                "position": err["position"],
                "code": err["code"],
            })
    return ak3_list


if __name__ == "__main__":
    import sys, os, json
    sys.path.insert(0, os.path.dirname(__file__))
    from tokenizer import tokenize
    from parser_204 import find_transactions, parse_204_transaction
    from validate import validate_envelope, validate_all

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

    input_filename = sys.argv[1] if len(sys.argv) > 1 else "sample_204_malformed.edi"
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )
    text = open(input_path).read()
    delims, segments = tokenize(text)

    for txn in find_transactions(segments):
        txn_errors = validate_all(txn)
        parsed = parse_204_transaction(txn)

        print("=== Machine-readable errors ===")
        print(json.dumps(txn_errors, indent=2))

        print("\n=== Plain-English error log ===")
        for line in build_error_log(
            txn_errors, parsed.get("shipment_id"), parsed.get("po_number")
        ):
            print(line)

        print("\n=== AK3/AK4 detail ===")
        print(json.dumps(to_ak3_ak4(txn_errors), indent=2))

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        log_path = os.path.join(OUTPUT_DIR, "error_log.txt")
        write_error_log(
            txn_errors, log_path,
            parsed.get("shipment_id"), parsed.get("po_number")
        )
        print(f"\nWrote {log_path}")
