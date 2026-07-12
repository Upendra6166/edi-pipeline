"""
generator.py — builds outbound 997 (Functional Acknowledgment) and
990 (Response to a Load Tender) X12 documents from a parsed 204.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from tokenizer import Delimiters, join_segments


class ControlNumberGenerator:
    """Simple incrementing counter for ISA13/GS06/ST02 control numbers."""
    def __init__(self, start=1):
        self._n = start

    def next(self):
        val = self._n
        self._n += 1
        return val


def build_997(gs_control_number, st_type, st_control_number, delims,
               control_gen, ack_status="A", sender_id="RDWYCARRIER",
               receiver_id="ULSH"):
    """
    gs_control_number / st_type / st_control_number: pulled from the
    INBOUND 204 you're acknowledging.
    ack_status: "A" (accept), "E" (accept with errors), "R" (reject).
    """
    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         "260709", "0900", "U", "00401", isa_ctrl, "0", "P", ">"],
        ["GS", "FA", sender_id, receiver_id, "20260709", "0900",
         gs_ctrl, "X", "004010"],
        ["ST", "997", st_ctrl],
        ["AK1", "SM", gs_control_number],
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


def build_990(shipment_id, delims, control_gen, reservation_code="A",
               sender_id="RDWYCARRIER", receiver_id="ULSH"):
    """
    shipment_id: the SI-qualified value from the parsed 204 (parsed["shipment_id"]).
    reservation_code: "A" = accept, "D" = decline.
    """
    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         "260709", "0900", "U", "00401", isa_ctrl, "0", "P", ">"],
        ["GS", "AR", sender_id, receiver_id, "20260709", "0900",
         gs_ctrl, "X", "004010"],
        ["ST", "990", st_ctrl],
        ["B1", sender_id, shipment_id or "", "20260709", reservation_code],
        ["L11", shipment_id or "", "SI"],
    ]

    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = (len(segments) - st_index) + 1
    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)


if __name__ == "__main__":
    import os
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

    from tokenizer import tokenize
    from parser_204 import find_transactions, parse_204_transaction

    with open(os.path.join(DATA_DIR, "sample_204_clean.edi")) as f:
        text = f.read()

    delims, segments = tokenize(text)
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)

    cg = ControlNumberGenerator(start=900001)

    ack_997 = build_997(
        gs_control_number="482",  # from GS06 of the inbound file
        st_type=parsed["st_transaction_type"],
        st_control_number=parsed["st_control_number"],
        delims=delims,
        control_gen=cg,
        ack_status="A",
    )
    print("=== 997 ===")
    print(ack_997)

    resp_990 = build_990(parsed["shipment_id"], delims, cg)
    print("\n=== 990 ===")
    print(resp_990)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "ack_997.edi"), "w") as f:
        f.write(ack_997)
    with open(os.path.join(OUTPUT_DIR, "response_990.edi"), "w") as f:
        f.write(resp_990)
    print(f"\nWrote files to {OUTPUT_DIR}")
