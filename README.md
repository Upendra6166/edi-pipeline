# EDI Load Tender Processing Pipeline

A small EDI pipeline for a transportation management system: parses inbound X12 004010 Motor Carrier Load Tenders (204), validates them, and generates outbound 997 (Functional Acknowledgment) and 990 (Response to Load Tender) documents. Built without any commercial/open-source X12 translation library — all parsing and generation is done directly against the segment/element structure.

## Approach

**Pipeline stages, each its own module:**
- `tokenizer.py` — detects delimiters dynamically from fixed ISA positions (element separator at byte 3, component separator at byte 104, segment terminator at byte 105), then splits raw text into segments and elements. Also provides the reverse operation (`join_segments`) used by the generator.
- `parser_204.py` — walks a tokenized 204 transaction as a small state machine (tracking whether we're in the header or inside a stop loop) and builds a structured dict: shipment ID, PO number, payment terms, equipment, stops (with appointment, address, and contact info), and totals.
- `validate.py` — structural/syntactic checks that operate on raw segments: envelope control number matching (ISA/IEA, GS/GE), ST/SE control number and segment count matching, unrecognized segment detection, and calendar date validity. Every check returns a list of errors rather than raising, so one bad transaction never crashes the pipeline.
- `validator.py` — business-rule checks that operate on the *parsed* dict: required-field completeness and basic format checks (numeric weight/charge, valid stop dates), producing AK3-ready error detail.
- `generator.py` — builds outbound 997s and 990s as plain Python lists of segments, computes SE counts by literally counting what was written (never hardcoded), and serializes with the same delimiters the inbound file used. `build_997_group` produces one 997 covering a whole functional group (used for both single-transaction and multi-transaction/batch files), with AK9 reporting "A"/"R"/"P" (partial-accept) based on the real mix of outcomes.
- `batch.py` — orchestrates a full interchange with multiple transactions, processing each independently so one bad transaction doesn't block the rest.

**Testing:** `tests/test_pipeline.py` covers delimiter detection (against two different trading partners' delimiter sets), envelope validation, SE count checking, unrecognized-segment and invalid-date detection, parser correctness, batch partial-accept behavior, and round-trip validation of generated output. Sample files are auto-discovered by filename keyword rather than hardcoded, and several tests inject synthetic corruption onto the clean sample so the suite doesn't depend entirely on the specific wording of one malformed file.

## Assumptions about the trading partner spec

Since no implementation guide was provided, field mappings were inferred from the sample files:
- `L11` qualifier `SI` = shipment ID, `PO` = purchase order number.
- `B2`'s last element is payment terms (e.g. `PP` = prepaid).
- `B2A02` is the tender purpose code (`LT` = load tender).
- `N7`'s equipment type is at position 2; equipment length is inferred as the last purely-numeric element in the segment, since its exact position varied and wasn't reliably fixed across the samples.
- `S5` reason codes `CL`/`LD` are treated as pickups, `CU`/`UL` as deliveries; any other code is recorded but labeled "other."
- `N1` entity code `BT` at the header level (before any `S5`) is the bill-to party; `N1` inside a stop loop is that stop's facility.
- A real trading partner's implementation guide would need to confirm all of the above, particularly the `N7` length position and any additional reference qualifiers not present in the provided samples.

## Known limitations

- **`validator.py`'s business rules are intentionally simple** (required-field presence, numeric/date format checks) and don't encode this partner's full business logic — e.g. no cross-field consistency checks (does total weight roughly match the sum of per-stop weights, if provided) or lookup-table validation (are `city`/`state`/`zip` internally consistent).
- **AK4 (element-level) detail isn't implemented** — errors are reported at the AK3 (segment) level only. Real trading partner certification usually expects AK4 pointing at the specific bad element within a segment.
- **No persistent control number storage.** `ControlNumberGenerator` resets on every run; a production system needs control numbers to never repeat across process restarts, which requires persisting the last-used number somewhere durable (database, file with locking, etc.).
- **Sample file auto-discovery is keyword-based** (matches "clean", "malformed", "multi"/"batch" in the filename) rather than pinned to exact filenames. This is convenient for testing against a renamed or swapped-in file, but means adding a new file whose name happens to contain one of those keywords could silently change which file a test runs against, depending on alphabetical sort order.
- **Only the 204/997/990 transaction set trio is supported.** No 210 (invoice), 214 (status update), or other transaction types.
- **Single-threaded, synchronous, no queueing or retry logic** — appropriate for this exercise, not for a production inbound EDI mailbox under load.
- **No encryption/authentication handling** (e.g. AS2, SFTP credentials, VAN mailboxing) — this pipeline assumes raw X12 text is already available on disk.

## What I'd add before running this against real trading partners

1. **Schema-driven validation** against a real X12 004010 implementation guide (segment/element requirement, min/max length, valid code lists) rather than the hand-derived checks here.
2. **AK4 element-level error detail**, and a proper error-code lookup table (the X12 standard has specific numeric codes for "required data element missing," "invalid character," etc., which this project currently approximates with a placeholder code).
3. **Persistent, thread-safe control number generation**, likely backed by a database sequence or an atomically-incremented file.
4. **Partner-specific configuration** (delimiter preferences, ID qualifiers, date formats) stored per trading partner rather than inferred at runtime, since real partners can and do deviate from what's inferable from one sample file.
5. **Structured logging and metrics** (which transactions were accepted/rejected, processing latency, error rate by code) for operational visibility — currently this pipeline only prints to stdout and writes output files.
6. **Retry and dead-letter handling** for transactions that fail unexpectedly (as opposed to failing validation, which is already handled gracefully).
7. **Support for additional transaction sets** (210, 214) and the ability to route inbound files to the right parser based on ST01.
8. **Automated round-trip / conformance testing** against multiple real trading partners' actual historical files, not just the 3 provided samples, to catch partner-specific quirks before they hit production.

## How to run

Run all commands from the `src/` directory (where the `.py` files live):

```bash
cd src

# Parse a single 204 and print the structured dict it produces
python parser_204.py sample_204_clean.edi

# Run structural + business validation on a broken 204 and print the errors
python validate.py sample_204_malformed.edi

# Full pipeline for one interchange: validate, then generate a 997 + 990
python generator.py sample_204_clean.edi

# Turn validation errors into a plain-English log plus AK3/AK4 detail
python error_log.py sample_204_malformed.edi

# Batch mode: multiple transactions in one interchange, partial-accept 997
python batch.py sample_multi_204_interchange.edi

# Run the test suite
python -m pytest tests/test_pipeline.py -v
```

Output files (parsed JSON, `ack_997*.edi`, `response_990_*.edi`, `batch_errors.json`, `error_log.txt`) are written to `../output/`, which is created automatically if it doesn't already exist.
