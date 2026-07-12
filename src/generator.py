"""
generator.py — builds outbound 997 (Functional Acknowledgment) and
990 (Response to a Load Tender) X12 documents from a parsed 204.

Nothing here is hardcoded to one trading partner: sender/receiver IDs
are derived (and swapped) from the inbound file's own ISA segment,
timestamps come from the system clock, and control numbers come from
the inbound file's own GS06 — not typed in by hand.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from tokenizer import join_segments


class ControlNumberGenerator:
    """Simple incrementing counter for ISA13/GS06/ST02 control numbers."""
    def __init__(self, start=1):
        self._n = start

    def next(self):
        val = self._n
        self._n += 1
        return val


def _now():
    """Returns (YYMMDD, YYYYMMDD, HHMM) for the current moment, used to
    stamp outbound ISA/GS dates and times."""
    now = datetime.now()
    return now.strftime("%y%m%d"), now.strftime("%Y%m%d"), now.strftime("%H%M")


def build_997(original_meta, st_type, st_control_number, delims,
               control_gen, ack_status="A"):
    """
    original_meta: dict from parser_204.extract_interchange_metadata()
                   run on the INBOUND file being acknowledged.
    st_type / st_control_number: ST01/ST02 of the inbound transaction
                   being acknowledged.
    ack_status: "A" (accept), "E" (accept with errors), "R" (reject).

    We are replying, so WE become the sender and the original sender
    becomes our receiver — roles are swapped from the inbound file.
    """
    sender_id = original_meta["receiver_id"]
    receiver_id = original_meta["sender_id"]
    isa_date, gs_date, time_now = _now()

    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         isa_date, time_now, "U", "00401", isa_ctrl, "0", "P",
         delims.sub_elem_delim],
        ["GS", "FA", sender_id, receiver_id, gs_date, time_now,
         gs_ctrl, "X", "004010"],
        ["ST", "997", st_ctrl],
        ["AK1", "SM", original_meta["gs_control_number"]],
        ["AK2", st_type, st_control_number],
        ["AK5", ack_status],
        ["AK9", ack_status, "1", "1", "1" if ack_status == "A" else "0"],
    ]

    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = (len(segments) - st_index) + 1  # +1 for the SE segment itself
    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)


def build_990(original_meta, shipment_id, delims, control_gen,
               reservation_code="A"):
    """
    original_meta: same dict as above, from the inbound 204.
    shipment_id: parsed["shipment_id"] from the inbound 204.
    reservation_code: "A" = accept, "D" = decline.
    """
    sender_id = original_meta["receiver_id"]
    receiver_id = original_meta["sender_id"]
    isa_date, gs_date, time_now = _now()

    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         isa_date, time_now, "U", "00401", isa_ctrl, "0", "P",
         delims.sub_elem_delim],
        ["GS", "AR", sender_id, receiver_id, gs_date, time_now,
         gs_ctrl, "X", "004010"],
        ["ST", "990", st_ctrl],
        ["B1", sender_id, shipment_id or "", gs_date, reservation_code],
        ["L11", shipment_id or "", "SI"],
    ]

    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = (len(segments) - st_index) + 1
    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

    from tokenizer import tokenize
    from parser_204 import (
        find_transactions, parse_204_transaction, extract_interchange_metadata
    )

    import sys as _sys
    input_filename = _sys.argv[1] if len(_sys.argv) > 1 else "sample_204_clean.edi"
    # If the person passed a full/relative path that already exists as-is,
    # use it directly; otherwise treat it as a filename inside DATA_DIR.
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )

    with open(input_path) as f:
        text = f.read()

    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)

    cg = ControlNumberGenerator(start=900001)

    ack_997 = build_997(
        original_meta=meta,
        st_type=parsed["st_transaction_type"],
        st_control_number=parsed["st_control_number"],
        delims=delims,
        control_gen=cg,
        ack_status="A",
    )
    print("=== 997 ===")
    print(ack_997)

    resp_990 = build_990(meta, parsed["shipment_id"], delims, cg)
    print("\n=== 990 ===")
    print(resp_990)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "ack_997.edi"), "w") as f:
        f.write(ack_997)
    with open(os.path.join(OUTPUT_DIR, "response_990.edi"), "w") as f:
        f.write(resp_990)
    print(f"\nWrote files to {OUTPUT_DIR}")
