\# EDI Load Tender Processing Pipeline



A small EDI pipeline for a transportation management system: parses inbound

X12 004010 Motor Carrier Load Tenders (204), validates them, and generates

outbound 997 (Functional Acknowledgment) and 990 (Response to Load Tender)

documents. Built without any commercial/open-source X12 translation library —

all parsing and generation is done directly against the segment/element

structure.



\## Approach



\*\*Pipeline stages, each its own module:\*\*



\- `tokenizer.py` — detects delimiters dynamically from fixed ISA positions

&#x20; (element separator at byte 3, component separator at byte 104, segment

&#x20; terminator at byte 105), then splits raw text into segments and elements.

&#x20; Also provides the reverse operation (`join\_segments`) used by the generator.

\- `parser\_204.py` — walks a tokenized 204 transaction as a small state

&#x20; machine (tracking whether we're in the header or inside a stop loop) and

&#x20; builds a structured dict: shipment ID, PO number, payment terms, equipment,

&#x20; stops (with appointment, address, and contact info), and totals.

\- `validate.py` — structural/syntactic checks that operate on raw segments:

&#x20; envelope control number matching (ISA/IEA, GS/GE), ST/SE control number

&#x20; and segment count matching, unrecognized segment detection, and calendar

&#x20; date validity. Every check returns a list of errors rather than raising,

&#x20; so one bad transaction never crashes the pipeline.

\- `validator.py` — business-rule checks that operate on the \*parsed\* dict:

&#x20; required-field completeness and basic format checks (numeric weight/charge,

&#x20; valid stop dates), producing AK3-ready error detail.

\- `generator.py` — builds outbound 997s and 990s as plain Python lists of

&#x20; segments, computes SE counts by literally counting what was written (never

&#x20; hardcoded), and serializes with the same delimiters the inbound file used.

&#x20; `build\_997\_group` produces one 997 covering a whole functional group (used

&#x20; for both single-transaction and multi-transaction/batch files), with AK9

&#x20; reporting "A"/"R"/"P" (partial-accept) based on the real mix of outcomes.

\- `batch.py` — orchestrates a full interchange with multiple transactions,

&#x20; processing each independently so one bad transaction doesn't block the rest.



\*\*Testing:\*\* `tests/test\_pipeline.py` covers delimiter detection (against two

different trading partners' delimiter sets), envelope validation, SE count

checking, unrecognized-segment and invalid-date detection, parser correctness,

batch partial-accept behavior, and round-trip validation of generated output.

Sample files are auto-discovered by filename keyword rather than hardcoded,

and several tests inject synthetic corruption onto the clean sample so the

suite doesn't depend entirely on the specific wording of one malformed file.



\## Assumptions about the trading partner spec



Since no implementation guide was provided, field mappings were inferred

from the sample files:



\- `L11` qualifier `SI` = shipment ID, `PO` = purchase order number.

\- `B2`'s last element is payment terms (e.g. `PP` = prepaid).

\- `B2A02` is the tender purpose code (`LT` = load tender).

\- `N7`'s equipment type is at position 2; equipment length is inferred as

&#x20; the last purely-numeric element in the segment, since its exact position

&#x20; varied and wasn't reliably fixed across the samples.

\- `S5` reason codes `CL`/`LD` are treated as pickups, `CU`/`UL` as deliveries;

&#x20; any other code is recorded but labeled "other."

\- `N1` entity code `BT` at the header level (before any `S5`) is the bill-to

&#x20; party; `N1` inside a stop loop is that stop's facility.

\- A real trading partner's implementation guide would need to confirm all

&#x20; of the above, particularly the `N7` length position and any additional

&#x20; reference qualifiers not present in the provided samples.



\## Known limitations



\- \*\*`validator.py`'s business rules are intentionally simple\*\* (required-field

&#x20; presence, numeric/date format checks) and don't encode this partner's full

&#x20; business logic — e.g. no cross-field consistency checks (does total weight

&#x20; roughly match the sum of per-stop weights, if provided) or lookup-table

&#x20; validation (are `city`/`state`/`zip` internally consistent).

\- \*\*AK4 (element-level) detail isn't implemented\*\* — errors are reported at

&#x20; the AK3 (segment) level only. Real trading partner certification usually

&#x20; expects AK4 pointing at the specific bad element within a segment.

\- \*\*No persistent control number storage.\*\* `ControlNumberGenerator` resets

&#x20; on every run; a production system needs control numbers to never repeat

&#x20; across process restarts, which requires persisting the last-used number

&#x20; somewhere durable (database, file with locking, etc.).

\- \*\*Sample file auto-discovery is keyword-based\*\* (matches "clean",

&#x20; "malformed", "multi"/"batch" in the filename) rather than pinned to exact

&#x20; filenames. This is convenient for testing against a renamed or swapped-in

&#x20; file, but means adding a new file whose name happens to contain one of

&#x20; those keywords could silently change which file a test runs against,

&#x20; depending on alphabetical sort order.

\- \*\*Only the 204/997/990 transaction set trio is supported.\*\* No 210

&#x20; (invoice), 214 (status update), or other transaction types.

\- \*\*Single-threaded, synchronous, no queueing or retry logic\*\* — appropriate

&#x20; for this exercise, not for a production inbound EDI mailbox under load.

\- \*\*No encryption/authentication handling\*\* (e.g. AS2, SFTP credentials,

&#x20; VAN mailboxing) — this pipeline assumes raw X12 text is already available

&#x20; on disk.



\## What I'd add before running this against real trading partners



1\. \*\*Schema-driven validation\*\* against a real X12 004010 implementation

&#x20;  guide (segment/element requirement, min/max length, valid code lists)

&#x20;  rather than the hand-derived checks here.

2\. \*\*AK4 element-level error detail\*\*, and a proper error-code lookup table

&#x20;  (the X12 standard has specific numeric codes for "required data element

&#x20;  missing," "invalid character," etc., which this project currently

&#x20;  approximates with a placeholder code).

3\. \*\*Persistent, thread-safe control number generation\*\*, likely backed by

&#x20;  a database sequence or an atomically-incremented file.

4\. \*\*Partner-specific configuration\*\* (delimiter preferences, ID qualifiers,

&#x20;  date formats) stored per trading partner rather than inferred at runtime,

&#x20;  since real partners can and do deviate from what's inferable from one

&#x20;  sample file.

5\. \*\*Structured logging and metrics\*\* (which transactions were accepted/

&#x20;  rejected, processing latency, error rate by code) for operational

&#x20;  visibility — currently this pipeline only prints to stdout and writes

&#x20;  output files.

6\. \*\*Retry and dead-letter handling\*\* for transactions that fail unexpectedly

&#x20;  (as opposed to failing validation, which is already handled gracefully).

7\. \*\*Support for additional transaction sets\*\* (210, 214) and the ability

&#x20;  to route inbound files to the right parser based on ST01.

8\. \*\*Automated round-trip / conformance testing\*\* against multiple real

&#x20;  trading partners' actual historical files, not just the 3 provided

&#x20;  samples, to catch partner-specific quirks before they hit production.



\## How to run



Run all commands from the src/ directory (where the .py files live):



cd src



\# Parse a single 204 and print the structured dict

python parser\_204.py sample\_204\_clean.edi



\# Run structural + business validation and print errors

python validate.py sample\_204\_malformed.edi



\# Full single-interchange pipeline: validate, then generate a 997 + 990

python generator.py sample\_204\_clean.edi



\# Turn validation errors into a plain-English log + AK3/AK4 detail

python error\_log.py sample\_204\_malformed.edi



\# Batch mode: multiple transactions in one interchange, partial-accept 997

python batch.py sample\_multi\_204\_interchange.edi



\# Run the test suite

python -m pytest tests/test\_pipeline.py -v







Output files (parsed JSON, ack\_997\*.edi, response\_990\_\*.edi, batch\_errors.json, error\_log.txt) get written to ../output/, which is created automatically if it doesn't exist.

