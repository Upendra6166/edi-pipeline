"""
generator.py — builds outbound 997 (Functional Acknowledgment) and
990 (Response to a Load Tender) X12 documents from a parsed 204.

Nothing here is hardcoded to one trading partner: sender/receiver IDs
are derived (and swapped) from the inbound file's own ISA segment,
timestamps come from the system clock, and control numbers come from
the inbound file's own GS06.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from tokenizer import join_segments


class ControlNumberGenerator:
    """Generates control numbers for ISA13, GS06 and ST02."""

    def __init__(self, start=1):
        self._n = start

    def next(self):
        value = self._n
        self._n += 1
        return value


def _now():
    """Returns (YYMMDD, YYYYMMDD, HHMM)."""

    now = datetime.now()
    return (
        now.strftime("%y%m%d"),
        now.strftime("%Y%m%d"),
        now.strftime("%H%M")
    )

def build_997(original_meta, st_type, st_control_number, delims,
              control_gen, ack_status="A", ak3_errors=None):
    """
    Builds an outbound 997 Functional Acknowledgment.

    ack_status:
        A = Accepted
        E = Accepted With Errors
        R = Rejected

    ak3_errors:
        [
            {
                "segment_id": "B2",
                "position": 3,
                "code": "8"
            }
        ]
    """

    # Since this is a reply, sender and receiver are swapped.
    sender_id = original_meta["receiver_id"]
    receiver_id = original_meta["sender_id"]

    isa_date, gs_date, time_now = _now()

    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    # Derived from the inbound file, not assumed: the functional ID code
    # this 997 is acknowledging (e.g. "SM" for 204s), and whether the
    # inbound interchange was production or test data — a 997 should
    # match that, not always claim "P".
    functional_id_code = original_meta.get("gs_functional_id_code", "SM")
    usage_indicator = original_meta.get("isa_usage_indicator", "P")

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         isa_date, time_now, "U", "00401", isa_ctrl, "0", usage_indicator,
         delims.sub_elem_delim],

        ["GS", "FA", sender_id, receiver_id,
         gs_date, time_now, gs_ctrl, "X", "004010"],

        ["ST", "997", st_ctrl],
        ["AK1", functional_id_code, original_meta["gs_control_number"]],
        ["AK2", st_type, st_control_number],
    ]

    # Add AK3 segments only if validation errors exist.
    for err in ak3_errors or []:
        segments.append(
            ["AK3", err["segment_id"], str(err["position"]),
             "", err["code"]]
        )

    # Transaction Acknowledgment
    segments.append(["AK5", ack_status])

    # Functional Group Acknowledgment
    segments.append(["AK9", ack_status, "1", "1",
                     "1" if ack_status == "A" else "0"])

    # Calculate SE segment count
    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = len(segments) - st_index + 1

    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)


def build_997_group(original_meta, txn_results, delims, control_gen):
    """
    Builds ONE outbound 997 covering MULTIPLE transactions in the same
    functional group — used for batch processing (Part 3B).

    txn_results: list of dicts, one per inbound transaction, each with:
        {
            "st_type": "204",
            "st_control_number": "0001",
            "ack_status": "A" or "R",
            "ak3_errors": [...] (list, possibly empty),
        }

    Structure: one AK1 for the whole group, then one AK2 (+ optional
    AK3s + AK5) per transaction, then one AK9 summarizing the group.
    AK9's first element is "A" only if every transaction was accepted,
    "R" if every transaction was rejected, and "P" (partial) if it's
    a mix — exactly what "AK9 partial-accept" means for a batch.
    """
    sender_id = original_meta["receiver_id"]
    receiver_id = original_meta["sender_id"]
    isa_date, gs_date, time_now = _now()

    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    # Derived from the inbound file, not assumed: the functional ID code
    # this 997 is acknowledging (e.g. "SM" for 204s), and whether the
    # inbound interchange was production or test data — a 997 should
    # match that, not always claim "P".
    functional_id_code = original_meta.get("gs_functional_id_code", "SM")
    usage_indicator = original_meta.get("isa_usage_indicator", "P")

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         isa_date, time_now, "U", "00401", isa_ctrl, "0", usage_indicator,
         delims.sub_elem_delim],
        ["GS", "FA", sender_id, receiver_id, gs_date, time_now,
         gs_ctrl, "X", "004010"],
        ["ST", "997", st_ctrl],
        ["AK1", functional_id_code, original_meta["gs_control_number"]],
    ]

    for txn in txn_results:
        segments.append(["AK2", txn["st_type"], txn["st_control_number"]])
        for err in txn.get("ak3_errors") or []:
            segments.append(
                ["AK3", err["segment_id"], str(err["position"]), "", err["code"]]
            )
        segments.append(["AK5", txn["ack_status"]])

    accepted = sum(1 for t in txn_results if t["ack_status"] == "A")
    rejected = sum(1 for t in txn_results if t["ack_status"] == "R")
    total = len(txn_results)

    if accepted == total:
        group_status = "A"
    elif rejected == total:
        group_status = "R"
    else:
        group_status = "P"  # partial accept — the mixed-outcome case

    segments.append(["AK9", group_status, str(total), str(total), str(accepted)])

    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = (len(segments) - st_index) + 1
    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)



def build_990(original_meta, shipment_id, delims,
              control_gen, reservation_code="A"):
    """Builds an outbound 990 Response to Load Tender."""

    sender_id = original_meta["receiver_id"]
    receiver_id = original_meta["sender_id"]

    isa_date, gs_date, time_now = _now()

    isa_ctrl = str(control_gen.next()).zfill(9)
    gs_ctrl = str(control_gen.next())
    st_ctrl = "0001"

    # Same reasoning as build_997/build_997_group: don't assume "P".
    usage_indicator = original_meta.get("isa_usage_indicator", "P")

    segments = [
        ["ISA", "00", "          ", "00", "          ",
         "02", sender_id.ljust(15), "02", receiver_id.ljust(15),
         isa_date, time_now, "U", "00401", isa_ctrl, "0", usage_indicator,
         delims.sub_elem_delim],

        ["GS", "AR", sender_id, receiver_id,
         gs_date, time_now, gs_ctrl, "X", "004010"],

        ["ST", "990", st_ctrl],
        ["B1", sender_id, shipment_id or "", gs_date, reservation_code],
        ["L11", shipment_id or "", "SI"],
    ]

    st_index = next(i for i, s in enumerate(segments) if s[0] == "ST")
    se_count = len(segments) - st_index + 1

    segments.append(["SE", str(se_count), st_ctrl])
    segments.append(["GE", "1", gs_ctrl])
    segments.append(["IEA", "1", isa_ctrl])

    return join_segments(segments, delims)


if __name__ == "__main__":

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

    from tokenizer import tokenize
    from parser_204 import find_transactions, parse_204_transaction, extract_interchange_metadata
    from validate import validate_all, to_ak3_errors
    from validator import validate_204

    import sys as _sys

    filename = _sys.argv[1] if len(_sys.argv) > 1 else "sample_204_clean.edi"
    input_file = filename if os.path.isfile(filename) else os.path.join(DATA_DIR, filename)

    with open(input_file) as f:
        text = f.read()

    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    transactions = find_transactions(segments)
    control_gen = ControlNumberGenerator(900001)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\nFound {len(transactions)} Transaction(s)\n")

    # First pass: parse and validate every transaction independently.
    # One bad transaction here does not stop the others from being
    # processed — each result is recorded and we move on.
    txn_results = []   # feeds the single group-level 997
    parsed_list = []   # kept alongside so we can still build per-shipment 990s

    for index, transaction in enumerate(transactions, 1):
        parsed = parse_204_transaction(transaction)

        structural_errors = validate_all(transaction)  # SE count, ZZZ, bad dates
        business_errors = validate_204(parsed)          # required fields, formats
        errors = to_ak3_errors(structural_errors, transaction) + business_errors

        ack_status = "R" if errors else "A"
        reservation_code = "D" if errors else "A"

        txn_results.append({
            "st_type": parsed["st_transaction_type"],
            "st_control_number": parsed["st_control_number"],
            "ack_status": ack_status,
            "ak3_errors": errors,
        })
        parsed_list.append((index, parsed, reservation_code))

        status_word = "ACCEPTED" if ack_status == "A" else "REJECTED"
        print(f"Transaction {index}: shipment {parsed['shipment_id']} -> {status_word}"
              + (f" ({[e.get('code', e) for e in errors]})" if errors else ""))

    # One 997 for the WHOLE group — whether it's a single transaction
    # (Part 1/2) or a full batch (Part 3B). AK9 naturally reflects "A"
    # when everything passed, "R" when everything failed, and "P"
    # (partial accept) when it's a genuine mix.
    ack_997 = build_997_group(meta, txn_results, delims, control_gen)
    ack_997_path = os.path.join(OUTPUT_DIR, "ack_997.edi")
    with open(ack_997_path, "w") as f:
        f.write(ack_997)

    print(f"\n997 (covers all {len(transactions)} transaction(s))\n{ack_997}\n")

    # A 990 is still generated per shipment — accepting or declining a
    # specific load tender is inherently a per-shipment response, unlike
    # the 997 which acknowledges the whole functional group at once.
    for index, parsed, reservation_code in parsed_list:
        resp_990 = build_990(
            meta, parsed["shipment_id"], delims, control_gen, reservation_code
        )
        out_path = os.path.join(OUTPUT_DIR, f"response_990_{index}.edi")
        with open(out_path, "w") as f:
            f.write(resp_990)
        print(f"990 for transaction {index}\n{resp_990}\n")

    print(f"Generated 1 group 997 + {len(transactions)} transaction 990(s)")
    print(f"Output Folder : {OUTPUT_DIR}")
