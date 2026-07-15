"""
tokenizer.py — dynamic delimiter detection and segment/element splitting
for ANSI X12 files.
"""


class Delimiters:
    def __init__(self, elem_delim, sub_elem_delim, seg_terminator):
        self.elem_delim = elem_delim
        self.sub_elem_delim = sub_elem_delim
        self.seg_terminator = seg_terminator

    def __repr__(self):
        return (f"Delimiters(element='{self.elem_delim}', "
                f"sub_element='{self.sub_elem_delim}', "
                f"segment='{self.seg_terminator}')")


def detect_delimiters(raw_text: str) -> Delimiters:
    if len(raw_text) < 107:
        raise ValueError("File too short to contain a valid ISA segment")

    if raw_text[0:3] != "ISA":
        raise ValueError("File does not start with ISA segment")

    elem_delim = raw_text[3]
    sub_elem_delim = raw_text[104]
    seg_terminator = raw_text[105]

    return Delimiters(elem_delim, sub_elem_delim, seg_terminator)


def split_segments(raw_text: str, delims: Delimiters) -> list[str]:
    raw_segments = raw_text.split(delims.seg_terminator)
    return [seg.strip() for seg in raw_segments if seg.strip()]


def split_elements(segment: str, delims: Delimiters) -> list[str]:
    return segment.split(delims.elem_delim)


def tokenize(raw_text: str) -> tuple[Delimiters, list[list[str]]]:
    delims = detect_delimiters(raw_text)
    raw_segments = split_segments(raw_text, delims)
    segments = [split_elements(seg, delims) for seg in raw_segments]
    return delims, segments


def join_elements(elements: list, delims: Delimiters) -> str:
    """Reverse of split_elements — used by the generator."""
    return delims.elem_delim.join(elements)


def join_segments(segment_lists: list, delims: Delimiters) -> str:
    """Reverse of tokenize — joins segments back into a raw X12 string."""
    joined = [join_elements(seg, delims) for seg in segment_lists]
    return delims.seg_terminator.join(joined) + delims.seg_terminator


if __name__ == "__main__":
    import sys
    import os
    import json

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "..", "data")

    input_filename = sys.argv[1] if len(sys.argv) > 1 else "sample_204_clean.edi"
    input_path = (
        input_filename if os.path.isfile(input_filename)
        else os.path.join(DATA_DIR, input_filename)
    )

    with open(input_path, "r") as f:
        text = f.read()

    delims, segments = tokenize(text)
    print(f"Detected delimiters: {delims}")
    print(f"Total segments: {len(segments)}")
    print(json.dumps(segments, indent=2))
