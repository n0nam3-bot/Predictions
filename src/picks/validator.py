"""Hard gate for LLM text: every number and name must trace to the facts packet."""
import re

NUM_RE = re.compile(r"(?<![\w.])[-+\u2212]?\d+(?:\.\d+)?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019.\-]*")
CAP_RE = re.compile(r"\b[A-Z][A-Za-z'\u2019.\-]*\b")
GENERIC = {"PLAY", "PASS", "NO", "BET", "ML", "ET", "UTC", "ATS", "EPA", "FIP", "ERA", "NBA", "NFL", "NHL", "MLB",
           "UFC", "DWCS", "KO", "TKO", "SUB", "DEC", "OT", "PP", "PK", "SLPM", "SAPM", "I", "A", "TOP", "PICK",
           "MMA", "VS", "VS.", "AM", "PM"}
UNAVAILABLE_WORDS = re.compile(r"unavailable|not available|no data|not connected|missing|not provided|unknown",
                               re.I)


def numbers_in(text):
    out = []
    for tok in NUM_RE.findall(text):
        out.append(abs(float(tok.replace("\u2212", "-"))))
    return out


def _walk(obj, nums, words):
    if isinstance(obj, dict):
        for k, v in obj.items():
            words.update(w.lower() for w in WORD_RE.findall(str(k)))
            _walk(v, nums, words)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, nums, words)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        x = abs(float(obj))
        nums.add(x)
        if x < 1.5:                                  # probabilities and edges also appear as percents
            for d in (0, 1, 2):
                nums.add(round(x * 100, d))
            nums.add(float(int(x * 100)))
        nums.add(round(x))
    elif isinstance(obj, str):
        nums.update(numbers_in(obj))
        words.update(w.lower().strip(".") for w in WORD_RE.findall(obj))


def allowed_sets(*sources):
    nums, words = set(), set()
    for s in sources:
        _walk(s, nums, words)
    return nums, words


def check_narrative(text, packet, model=None, tol=0.051):
    """Return a list of problems (empty list = passes)."""
    nums, words = allowed_sets(packet, model or {})
    problems = []
    for n in numbers_in(text):
        if not any(abs(n - a) <= tol for a in nums):
            problems.append(f"number not in the data: {n:g}")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        toks = CAP_RE.findall(sentence)
        first = WORD_RE.search(sentence)
        for tok in toks:
            if first and sentence[first.start():first.end()] == tok and sentence.lstrip().startswith(tok):
                continue                              # sentence-initial capital is not a name
            t = tok.strip(".").lower()
            if t not in words and tok.upper().strip(".") not in GENERIC:
                problems.append(f"name or term not in the data: {tok}")
    for item in packet.get("unavailable", []):
        kws = [k.lower() for k in item.get("keywords", [])]
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if any(k in sentence.lower() for k in kws) and not UNAVAILABLE_WORDS.search(sentence):
                problems.append(f"claims about unavailable input '{item['key']}': {sentence[:60]}")
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
