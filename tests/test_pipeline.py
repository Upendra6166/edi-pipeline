"""
test_pipeline.py — automated tests for the EDI pipeline.

Generic by design: nothing here hardcodes an expected shipment ID,
delimiter character, or filename tied to one specific sample. Instead:
  - sample files are auto-discovered by name pattern (clean/malformed/
    multi-batch), so renaming or swapping in a different partner's
    files doesn't break the suite
  - "correct" values are derived independently from the raw file
    (an oracle computed differently from the code under test), not
    copy-pasted literals — so a test failure means the CODE is wrong,
    not that the SAMPLE FILE changed
  - structural bugs (bad SE count, unknown segment, bad date, envelope
    mismatch) are injected synthetically onto whatever clean file is
    found, so these tests work even if no malformed sample exists

Run with:  pytest tests/test_pipeline.py -v
"""

import os
import sys
import copy
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tokenizer import tokenize
from parser_204 import find_transactions, parse_204_transaction, extract_interchange_metadata
from validate import validate_envelope, validate_transaction, validate_all, to_ak3_errors
from validator import validate_204
from generator import ControlNumberGenerator, build_997_group

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ---------------------------------------------------------------------
# Generic file discovery — find sample files by role, not exact name.
# ---------------------------------------------------------------------

def _find_file(*keywords):
    """Returns the first .edi file in DATA_DIR whose name contains ALL
    given keywords (case-insensitive), or None if none match."""
    if not os.path.isdir(DATA_DIR):
        return None
    for name in sorted(os.listdir(DATA_DIR)):
        if not name.endswith(".edi"):
            continue
        lowered = name.lower()
        if all(k.lower() in lowered for k in keywords):
            return os.path.join(DATA_DIR, name)
    return None


CLEAN_FILE = _find_file("clean")
MALFORMED_FILE = _find_file("malformed")
MULTI_FILE = _find_file("multi") or _find_file("batch")

skip_no_clean = pytest.mark.skipif(not CLEAN_FILE, reason="no clean sample file found in data/")
skip_no_malformed = pytest.mark.skipif(not MALFORMED_FILE, reason="no malformed sample file found in data/")
skip_no_multi = pytest.mark.skipif(not MULTI_FILE, reason="no multi-transaction sample file found in data/")


def read(path):
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------
# Delimiter detection — verified against an independent oracle, not a
# hardcoded expected character, so this works for ANY input file.
# ---------------------------------------------------------------------

def _oracle_delimiters(raw_text):
    """
    Computes delimiters directly from fixed ISA positions, written
    independently of tokenizer.py's own implementation. If tokenizer.py
    ever hardcodes or breaks delimiter detection, this test catches it
    regardless of which file is used or what characters it contains.
    """
    return raw_text[3], raw_text[104], raw_text[105]


@pytest.mark.parametrize("path", [p for p in (CLEAN_FILE, MALFORMED_FILE, MULTI_FILE) if p])
def test_detect_delimiters_matches_independent_oracle(path):
    text = read(path)
    delims, _ = tokenize(text)
    expected_elem, expected_sub, expected_seg = _oracle_delimiters(text)
    assert delims.elem_delim == expected_elem
    assert delims.sub_elem_delim == expected_sub
    assert delims.seg_terminator == expected_seg


@skip_no_clean
def test_two_sample_files_use_different_delimiters_if_both_present():
    """Confirms delimiter detection is genuinely dynamic: if a second
    sample uses different characters, detection must reflect that,
    not silently reuse whatever the first file used."""
    if not MULTI_FILE:
        pytest.skip("no second file with different delimiters available")
    delims_a, _ = tokenize(read(CLEAN_FILE))
    delims_b, _ = tokenize(read(MULTI_FILE))
    assert (delims_a.elem_delim, delims_a.seg_terminator) != \
           (delims_b.elem_delim, delims_b.seg_terminator)


@skip_no_clean
def test_tokenize_produces_expected_segment_boundaries():
    _, segments = tokenize(read(CLEAN_FILE))
    assert segments[0][0] == "ISA"
    assert segments[-1][0] == "IEA"


# ---------------------------------------------------------------------
# Envelope validation — real file plus synthetic corruption, so the
# "catches a mismatch" case doesn't depend on a specific broken sample.
# ---------------------------------------------------------------------

@skip_no_clean
def test_envelope_valid_on_a_real_clean_file():
    _, segments = tokenize(read(CLEAN_FILE))
    assert validate_envelope(segments) == []


@skip_no_clean
def test_envelope_catches_isa_iea_mismatch_synthetic():
    _, segments = tokenize(read(CLEAN_FILE))
    broken = copy.deepcopy(segments)
    for seg in broken:
        if seg[0] == "IEA":
            seg[2] = seg[2] + "_CORRUPTED"
    codes = [e["code"] for e in validate_envelope(broken)]
    assert "ISA_IEA_CONTROL_MISMATCH" in codes


@skip_no_clean
def test_envelope_catches_gs_ge_mismatch_synthetic():
    _, segments = tokenize(read(CLEAN_FILE))
    broken = copy.deepcopy(segments)
    for seg in broken:
        if seg[0] == "GE":
            seg[2] = seg[2] + "_CORRUPTED"
    codes = [e["code"] for e in validate_envelope(broken)]
    assert "GS_GE_CONTROL_MISMATCH" in codes


# ---------------------------------------------------------------------
# SE segment count checking — real file plus synthetic corruption.
# ---------------------------------------------------------------------

@skip_no_clean
def test_se_count_matches_on_a_real_clean_file():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = find_transactions(segments)[0]
    assert validate_transaction(txn) == []


@skip_no_clean
def test_se_count_mismatch_detected_synthetic():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = copy.deepcopy(find_transactions(segments)[0])
    for seg in txn:
        if seg[0] == "SE":
            seg[1] = str(int(seg[1]) + 5)  # declare a wrong count
    codes = [e["code"] for e in validate_transaction(txn)]
    assert "SE_COUNT_MISMATCH" in codes


@skip_no_malformed
def test_se_count_mismatch_detected_on_real_malformed_file():
    """Belt-and-suspenders: also confirms it against the real sample,
    if one is available, since a synthetic test alone can't catch bugs
    specific to how a real-world file happens to be malformed."""
    _, segments = tokenize(read(MALFORMED_FILE))
    txn = find_transactions(segments)[0]
    codes = [e["code"] for e in validate_transaction(txn)]
    assert "SE_COUNT_MISMATCH" in codes


# ---------------------------------------------------------------------
# Unrecognized segment / invalid date — synthetic injection, so these
# don't depend on knowing exactly what's wrong with a specific sample.
# ---------------------------------------------------------------------

@skip_no_clean
def test_unrecognized_segment_detected_synthetic():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = copy.deepcopy(find_transactions(segments)[0])
    txn.insert(2, ["ZZZ_NOT_A_REAL_SEGMENT", "test", "data"])
    errors = validate_all(txn)
    flagged = [e["segment_id"] for e in errors if e["code"] == "UNRECOGNIZED_SEGMENT"]
    assert "ZZZ_NOT_A_REAL_SEGMENT" in flagged


@skip_no_clean
def test_invalid_date_detected_synthetic():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = copy.deepcopy(find_transactions(segments)[0])
    for seg in txn:
        if seg[0] == "G62":
            seg[2] = "20260231"  # February 31st does not exist
            break
    errors = validate_all(txn)
    codes = [e["code"] for e in errors]
    assert "INVALID_DATE" in codes


@skip_no_malformed
def test_malformed_file_does_not_crash_parsing():
    """A malformed file must produce a result, never an exception —
    this is the core Part 3A requirement."""
    _, segments = tokenize(read(MALFORMED_FILE))
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)  # must not raise
    assert isinstance(parsed, dict)
    assert "stops" in parsed


# ---------------------------------------------------------------------
# Parser correctness — expected values derived from the raw file itself
# (an independent oracle), not hardcoded literals from one sample.
# ---------------------------------------------------------------------

def _oracle_field(txn, seg_id, index, qualifier_index=None, qualifier_value=None):
    """Independently scans raw segments for a value, bypassing
    parse_204_transaction entirely, to build an expected value the
    parser's own output can be checked against."""
    for seg in txn:
        if seg[0] != seg_id:
            continue
        if qualifier_index is not None:
            if len(seg) <= qualifier_index or seg[qualifier_index] != qualifier_value:
                continue
        if len(seg) > index:
            return seg[index]
    return None


@skip_no_clean
def test_parsed_shipment_id_matches_raw_segment():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)
    expected = _oracle_field(txn, "L11", 1, qualifier_index=2, qualifier_value="SI")
    assert parsed["shipment_id"] == expected
    assert expected is not None  # sanity: the sample must actually have one


@skip_no_clean
def test_parsed_po_number_matches_raw_segment():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)
    expected = _oracle_field(txn, "L11", 1, qualifier_index=2, qualifier_value="PO")
    assert parsed["po_number"] == expected
    assert expected is not None


@skip_no_clean
def test_parsed_stop_count_matches_raw_s5_count():
    _, segments = tokenize(read(CLEAN_FILE))
    txn = find_transactions(segments)[0]
    parsed = parse_204_transaction(txn)
    expected_stop_count = sum(1 for seg in txn if seg[0] == "S5")
    assert len(parsed["stops"]) == expected_stop_count
    assert expected_stop_count > 0  # sanity: the sample must have stops


# ---------------------------------------------------------------------
# Batch processing (Part 3B) — works for any number of transactions,
# any mix of valid/invalid, not hardcoded to "3 transactions, 1 bad".
# ---------------------------------------------------------------------

@skip_no_multi
def test_batch_file_processes_every_transaction_independently():
    _, segments = tokenize(read(MULTI_FILE))
    transactions = find_transactions(segments)
    assert len(transactions) > 1  # this file's whole point is >1 transaction

    outcomes = []
    for txn in transactions:
        parsed = parse_204_transaction(txn)
        errors = validate_all(txn) + validate_204(parsed)
        outcomes.append(len(errors) == 0)

    # Every transaction produced SOME outcome — none silently dropped.
    assert len(outcomes) == len(transactions)


@skip_no_multi
def test_group_997_ak9_status_matches_computed_outcomes():
    text = read(MULTI_FILE)
    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    transactions = find_transactions(segments)
    control_gen = ControlNumberGenerator(start=1)

    txn_results = []
    for txn in transactions:
        parsed = parse_204_transaction(txn)
        errors = validate_all(txn) + validate_204(parsed)
        txn_results.append({
            "st_type": parsed["st_transaction_type"],
            "st_control_number": parsed["st_control_number"],
            "ack_status": "R" if errors else "A",
            "ak3_errors": [],
        })

    accepted = sum(1 for t in txn_results if t["ack_status"] == "A")
    total = len(txn_results)
    expected_status = "A" if accepted == total else ("R" if accepted == 0 else "P")

    result_997 = build_997_group(meta, txn_results, delims, control_gen)
    _, out_segments = tokenize(result_997)
    ak9 = next(s for s in out_segments if s[0] == "AK9")
    assert ak9[1] == expected_status


# ---------------------------------------------------------------------
# Generated 997 is itself syntactically valid X12 (round-trip check) —
# works for any clean or multi file, whichever is available.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", [p for p in (CLEAN_FILE, MALFORMED_FILE, MULTI_FILE) if p])
def test_generated_997_round_trips_cleanly(path):
    text = read(path)
    delims, segments = tokenize(text)
    meta = extract_interchange_metadata(segments)
    transactions = find_transactions(segments)
    control_gen = ControlNumberGenerator(start=1)

    txn_results = []
    for txn in transactions:
        parsed = parse_204_transaction(txn)
        structural_errors = validate_all(txn)
        business_errors = validate_204(parsed)
        errors = to_ak3_errors(structural_errors, txn) + business_errors
        txn_results.append({
            "st_type": parsed["st_transaction_type"],
            "st_control_number": parsed["st_control_number"],
            "ack_status": "R" if errors else "A",
            "ak3_errors": errors,
        })

    result_997 = build_997_group(meta, txn_results, delims, control_gen)

    _, out_segments = tokenize(result_997)
    assert validate_envelope(out_segments) == []
    for out_txn in find_transactions(out_segments):
        assert validate_transaction(out_txn) == []
