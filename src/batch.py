"""
batch.py — processes a single interchange containing MULTIPLE 204
transactions (Part 3B). Each transaction is handled independently:
one bad transaction does not stop the others from being processed.

Outputs, per run:
  - output/parsed_<shipment_id>.json   for each VALID transaction
  - output/batch_errors.json           list of invalid transactions + reasons
  - output/ack_997_group.edi           ONE 997 covering the whole group,
                                        with AK9 reflecting partial-accept
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from tokenizer import tokenize
from parser_204 import find_transactions, parse_204_transaction, extract_interchange_metadata
from validate import validate_all, validate_envelope, to_ak3_errors
from validator import validate_204
from generator import ControlNumberGenerator, build_997_group


def process_batch(text):
    """
    Runs the full batch pipeline on raw interchange text.
    Returns (valid_results, invalid_results, group_997_text).
    """
    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    envelope_errors = validate_envelope(segments)  # checked once for the whole file

    transactions = find_transactions(segments)
    control_gen = ControlNumberGenerator(start=900001)

    valid_results = []
    invalid_results = []
    txn_results_for_997 = []

    for txn in transactions:
        try:
            parsed = parse_204_transaction(txn)
        except Exception as exc:
            invalid_results.append({
                "shipment_id": None,
                "st_control_number": None,
                "errors": [{"code": "PARSE_FAILURE", "message": str(exc)}],
            })
            continue

        structural_errors = validate_all(txn)
        business_errors = validate_204(parsed)
        all_errors = to_ak3_errors(structural_errors, txn) + business_errors

        ack_status = "R" if all_errors else "A"

        txn_results_for_997.append({
            "st_type": parsed.get("st_transaction_type"),
            "st_control_number": parsed.get("st_control_number"),
            "ack_status": ack_status,
            "ak3_errors": all_errors,
        })

        if all_errors:
            invalid_results.append({
                "shipment_id": parsed.get("shipment_id"),
                "st_control_number": parsed.get("st_control_number"),
                "errors": all_errors,
            })
        else:
            valid_results.append({
                "shipment_id": parsed.get("shipment_id"),
                "parsed": parsed,
            })

    group_997 = None
    if envelope_errors:
        invalid_results.insert(0, {
            "shipment_id": None,
            "st_control_number": None,
            "errors": envelope_errors,
        })
    elif txn_results_for_997:
        group_997 = build_997_group(meta, txn_results_for_997, delims, control_gen)

    return valid_results, invalid_results, group_997


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

    input_filename = sys.argv[1] if len(sys.argv) > 1 else "sample_multi_204_interchange.edi"
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )

    with open(input_path) as f:
        text = f.read()

    valid, invalid, group_997 = process_batch(text)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Processed batch: {len(valid)} valid, {len(invalid)} invalid\n")

    for v in valid:
        shipment_id = v["shipment_id"] or "UNKNOWN"
        out_path = os.path.join(OUTPUT_DIR, f"parsed_{shipment_id}.json")
        with open(out_path, "w") as f:
            json.dump(v["parsed"], f, indent=2)
        print(f"  VALID   shipment {shipment_id} -> {os.path.basename(out_path)}")

    for inv in invalid:
        shipment_id = inv["shipment_id"] or "UNKNOWN"
        codes = [e.get("code", "?") for e in inv["errors"]]
        print(f"  INVALID shipment {shipment_id} (ST {inv['st_control_number']}): {codes}")

    errors_path = os.path.join(OUTPUT_DIR, "batch_errors.json")
    with open(errors_path, "w") as f:
        json.dump(invalid, f, indent=2)
    print(f"\nWrote {errors_path}")

    if group_997:
        group_997_path = os.path.join(OUTPUT_DIR, "ack_997_group.edi")
        with open(group_997_path, "w") as f:
            f.write(group_997)
        print(f"Wrote {group_997_path}")
        print(f"\n{group_997}")
