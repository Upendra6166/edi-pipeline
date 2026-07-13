"""
parser_204.py — turns tokenized 204 segments into a structured dict.
"""


def get(seg, i, default=None):
    """Safely grab element i from a segment, or return default if missing."""
    return seg[i] if len(seg) > i else default


def find_transactions(segments):
    """Split full segment list into separate ST...SE transaction blocks."""
    transactions, current = [], None
    for seg in segments:
        if seg[0] == "ST":
            current = [seg]
        elif current is not None:
            current.append(seg)
            if seg[0] == "SE":
                transactions.append(current)
                current = None
    return transactions


def extract_interchange_metadata(segments):
    """Pulls ISA/GS/GE/IEA control numbers and sender/receiver IDs."""
    meta = {}
    for seg in segments:
        if seg[0] == "ISA":
            meta["isa_control_number"] = get(seg, 13)
            meta["sender_id"] = get(seg, 6, "").strip()
            meta["receiver_id"] = get(seg, 8, "").strip()
            meta["isa_usage_indicator"] = get(seg, 15, "P")  # "P"=production, "T"=test
        elif seg[0] == "IEA":
            meta["iea_control_number"] = get(seg, 2)
        elif seg[0] == "GS":
            meta["gs_control_number"] = get(seg, 6)
            meta["gs_functional_id_code"] = get(seg, 1)  # e.g. "SM" for 204s
        elif seg[0] == "GE":
            meta["ge_control_number"] = get(seg, 2)
    return meta


STOP_REASON_MAP = {"CL": "pickup", "CU": "delivery", "LD": "pickup", "UL": "delivery"}


def new_stop(seg, position):
    """Builds a fresh stop dict when an S5 segment starts a new loop.
    position: 1-based index of this S5 segment within the transaction,
    used to seed _positions so validators can point at real segments."""
    reason_code = get(seg, 2)
    return {
        "stop_number": get(seg, 1),
        "reason_code": reason_code,
        "reason": STOP_REASON_MAP.get(reason_code, "other"),
        "appointment_date": None, "appointment_time": None,
        "facility_name": None, "facility_id": None,
        "address_line1": None, "city": None, "state": None,
        "zip": None, "country": None,
        "contact_name": None, "contact_phone": None,
        "_positions": {"S5": position},
    }


# Each stop-level segment has its own tiny function that fills in the
# fields it owns. Adding a new stop-level segment later means adding
# one entry here — the main loop and position tracking don't change.
STOP_HANDLERS = {
    "G62": lambda stop, seg: stop.update(
        appointment_date=get(seg, 2), appointment_time=get(seg, 4)),
    "N1": lambda stop, seg: stop.update(
        facility_name=get(seg, 2), facility_id=get(seg, 4)),
    "N3": lambda stop, seg: stop.update(
        address_line1=get(seg, 1)),
    "N4": lambda stop, seg: stop.update(
        city=get(seg, 1), state=get(seg, 2), zip=get(seg, 3), country=get(seg, 4)),
    "G61": lambda stop, seg: stop.update(
        contact_name=get(seg, 2), contact_phone=get(seg, 4)),
}


def parse_204_transaction(txn_segments):
    """Parses ONE ST...SE transaction into a structured dict."""
    result = {"shipment_id": None, "po_number": None, "payment_terms": None,
               "tender_purpose": None, "equipment_type": None,
               "equipment_length": None, "total_weight": None,
               "total_charge": None, "stops": []}

    stops, stop, in_stops = [], None, False

    for position, seg in enumerate(txn_segments, start=1):
        sid = seg[0]

        if sid == "ST":
            result["st_transaction_type"] = get(seg, 1)
            result["st_control_number"] = get(seg, 2)

        elif sid == "SE":
            result["se_segment_count"] = get(seg, 1)
            result["se_control_number"] = get(seg, 2)

        elif sid == "B2":
            result["payment_terms"] = seg[-1] or None

        elif sid == "B2A":
            result["tender_purpose"] = get(seg, 2)

        elif sid == "L11" and not in_stops:
            qualifier, value = get(seg, 2), get(seg, 1)
            if qualifier == "SI":
                result["shipment_id"] = value
            elif qualifier == "PO":
                result["po_number"] = value

        elif sid == "N7":
            result["equipment_type"] = get(seg, 2)
            digits = [el for el in seg if el.strip().isdigit()]
            if digits:
                result["equipment_length"] = digits[-1]

        elif sid == "S5":
            in_stops = True
            if stop:
                stops.append(stop)
            stop = new_stop(seg, position)

        elif sid in STOP_HANDLERS and stop:
            STOP_HANDLERS[sid](stop, seg)
            stop["_positions"][sid] = position

        elif sid == "L3":
            if stop:
                stops.append(stop)
                stop = None
            result["total_weight"] = get(seg, 1)
            result["total_charge"] = get(seg, 5)

    if stop:  # safety net if file ends without an L3
        stops.append(stop)

    result["stops"] = stops
    return result


if __name__ == "__main__":
    import sys, os, json
    sys.path.insert(0, os.path.dirname(__file__))
    from tokenizer import tokenize

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")

    input_filename = sys.argv[1] if len(sys.argv) > 1 else "sample_204_clean.edi"
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )
    text = open(input_path).read()

    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    print(f"Metadata: {json.dumps(meta, indent=2)}")

    for i, txn in enumerate(find_transactions(segments)):
        parsed = parse_204_transaction(txn)
        print(f"\n--- Transaction {i + 1} ---")
        print(json.dumps(parsed, indent=2))
