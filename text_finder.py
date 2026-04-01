from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
import re
from typing import Iterable, Literal, Optional, Tuple

import pyautogui
import pytesseract

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def _debug_print(enabled: bool, msg: str) -> None:
    if enabled:
        print(msg)

_DEFAULT_TESSERACT_EXE = resource_path(r"Tesseract-OCR/tesseract.exe")
_DEFAULT_TESSDATA_DIR = resource_path(r"Tesseract-OCR/tessdata")


def _ensure_tesseract_configured(
    *,
    tesseract_cmd: Optional[str] = None,
    tessdata_dir: Optional[str] = None,
) -> None:
    tesseract_cmd = tesseract_cmd or _DEFAULT_TESSERACT_EXE
    tessdata_dir = tessdata_dir or _DEFAULT_TESSDATA_DIR

    if not os.path.exists(tesseract_cmd):
        raise FileNotFoundError(
            f"tesseract.exe not found at {tesseract_cmd!r}. "
            "Make sure the bundled Tesseract-OCR folder is present, or pass tesseract_cmd=..."
        )
    if not os.path.isdir(tessdata_dir):
        raise FileNotFoundError(
            f"tessdata folder not found at {tessdata_dir!r}. "
            "Make sure Tesseract-OCR/tessdata exists, or pass tessdata_dir=..."
        )

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    os.environ["TESSDATA_PREFIX"] = tessdata_dir


Region = Tuple[int, int, int, int]  # (left, top, width, height)
MatchStrategy = Literal["best", "first"]


@dataclass(frozen=True)
class OcrMatch:
    coords: Tuple[float, float]
    bbox: Tuple[int, int, int, int]  # (left, top, width, height) in screen coords
    confidence: float
    matched_text: str
    source_region: Region


def _get_window_region(window_title: str) -> Region:
    if gw is None:
        raise ImportError(
            "pygetwindow is required for window capture. Install it with: py -m pip install pygetwindow"
        )

    windows = gw.getWindowsWithTitle(window_title)
    if not windows:
        raise ValueError(f"No window found with title containing {window_title!r}.")

    win = windows[0]
    left = int(win.left)
    top = int(win.top)
    width = int(win.width)
    height = int(win.height)
    if width <= 0 or height <= 0:
        raise ValueError(f"Window {window_title!r} has invalid size: {width}x{height}.")
    return (left, top, width, height)


def _normalize_region(
    *,
    region: Optional[Region] = None,
    window_title: Optional[str] = None,
) -> Region:
    if region is not None and window_title is not None:
        raise ValueError("Pass only one of region= or window_title=.")

    if window_title:
        return _get_window_region(window_title)

    if region is not None:
        left, top, width, height = region
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid region size: {width}x{height}.")
        return (int(left), int(top), int(width), int(height))

    screen_w, screen_h = pyautogui.size()
    return (0, 0, int(screen_w), int(screen_h))


def _capture(region: Region):
    left, top, width, height = region
    return pyautogui.screenshot(region=(left, top, width, height))


def locate_text(
    word: str,
    letter: Optional[str] = None,
    debug: bool = False,
    *,
    window_title: Optional[str] = None,
    region: Optional[Region] = None,
) -> Optional[Tuple[float, float]]:
    """
    Backwards-compatible wrapper that returns only (x, y) or None.

    For the optimized API, use locate_text_match().
    """
    match = locate_text_match(
        word,
        letter=letter,
        debug=debug,
        window_title=window_title,
        region=region,
    )
    return None if match is None else match.coords


def _parse_region(s: str) -> Region:
    """
    Parse 'left,top,width,height' into a Region tuple.
    """
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("Region must be 'left,top,width,height'.")
    left, top, width, height = (int(p) for p in parts)
    return (left, top, width, height)


def _tesseract_config(*, psm: Optional[int]) -> str:
    # Keep config minimal; callers can tune psm for UI-like screens.
    if psm is None:
        return ""
    return f"--psm {int(psm)}"


def _iter_word_rows(data: dict) -> Iterable[dict]:
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        conf_raw = data.get("conf", ["-1"] * n)[i]
        try:
            conf = float(conf_raw)
        except Exception:
            conf = -1.0
        yield {
            "i": i,
            "text": text,
            "conf": conf,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
            # Optional line structure info. Present in pytesseract image_to_data output.
            "block_num": int(data.get("block_num", [0] * n)[i]),
            "par_num": int(data.get("par_num", [0] * n)[i]),
            "line_num": int(data.get("line_num", [0] * n)[i]),
            "word_num": int(data.get("word_num", [0] * n)[i]),
        }


def _union_bbox(rows: list[dict]) -> Tuple[int, int, int, int]:
    """
    Union bbox for rows in capture-image coordinates.
    Returns (left, top, width, height).
    """
    left = min(int(r["left"]) for r in rows)
    top = min(int(r["top"]) for r in rows)
    right = max(int(r["left"]) + int(r["width"]) for r in rows)
    bottom = max(int(r["top"]) + int(r["height"]) for r in rows)
    return (left, top, int(right - left), int(bottom - top))


def _select_phrase_match(
    *,
    rows: list[dict],
    phrase: str,
    min_conf: float,
    match_strategy: MatchStrategy,
    match_index: int,
    case_sensitive: bool,
) -> Optional[dict]:
    """
    Phrase matcher across adjacent word rows within the same OCR line.

    Returns a dict in the same shape as a word-row, but with bbox/confidence
    computed from the matched sequence of words.
    """
    if not phrase or not phrase.strip():
        return None

    # Normalize whitespace: treat any run of whitespace as a single space.
    phrase = " ".join(phrase.strip().split())

    if not case_sensitive:
        def norm(s: str) -> str:
            return s.casefold()
    else:
        def norm(s: str) -> str:
            return s

    tokens = [t for t in phrase.split(" ") if t]
    if not tokens:
        return None

    # Group by OCR line (block/par/line), then scan for a contiguous token match.
    line_groups: dict[tuple[int, int, int], list[dict]] = {}
    for r in rows:
        if r["conf"] < min_conf:
            continue
        key = (int(r.get("block_num", 0)), int(r.get("par_num", 0)), int(r.get("line_num", 0)))
        line_groups.setdefault(key, []).append(r)

    candidates: list[dict] = []
    for _, line_rows in line_groups.items():
        # Best effort ordering: word_num is usually reliable; fallback to left-to-right.
        line_rows_sorted = sorted(
            line_rows, key=lambda r: (int(r.get("word_num", 0)), int(r["left"]), int(r["top"]))
        )
        line_tokens = [norm(r["text"]) for r in line_rows_sorted]
        if len(line_tokens) < len(tokens):
            continue

        tokens_norm = [norm(t) for t in tokens]
        for start in range(0, len(line_tokens) - len(tokens_norm) + 1):
            window = line_tokens[start : start + len(tokens_norm)]
            if window != tokens_norm:
                continue

            matched_rows = line_rows_sorted[start : start + len(tokens_norm)]
            left, top, width, height = _union_bbox(matched_rows)
            conf = sum(float(r["conf"]) for r in matched_rows) / max(1, len(matched_rows))

            # Use the first row index for stable ordering; smaller i means earlier in OCR output.
            i0 = min(int(r["i"]) for r in matched_rows)
            candidates.append(
                {
                    "i": i0,
                    "text": phrase,  # preserve original spacing-normalized phrase
                    "conf": float(conf),
                    "left": int(left),
                    "top": int(top),
                    "width": int(width),
                    "height": int(height),
                }
            )

    if not candidates:
        return None

    if match_index < 0:
        raise ValueError("match_index must be >= 0.")

    if match_strategy == "first":
        # Preserve OCR order.
        ordered = sorted(candidates, key=lambda r: int(r["i"]))
        return ordered[match_index] if match_index < len(ordered) else None

    ranked = sorted(candidates, key=lambda r: (float(r["conf"]), -int(r["i"])), reverse=True)
    return ranked[match_index] if match_index < len(ranked) else None


def _tokenize_punct_phrase(s: str) -> list[str]:
    """
    Tokenize a phrase into alnum-runs and punctuation characters.

    Example: "my.name" -> ["my", ".", "name"]
    """
    s = s.strip()
    if not s:
        return []

    # Keep whitespace out; phrase matching across words is handled elsewhere.
    # This tokenizer is specifically for punctuation-separated single "words".
    s = "".join(ch for ch in s if not ch.isspace())
    if not s:
        return []

    # \w includes underscore; that's fine for many UI identifiers.
    return re.findall(r"\w+|[^\w]", s, flags=re.UNICODE)


def _select_punct_phrase_match(
    *,
    rows: list[dict],
    phrase: str,
    min_conf: float,
    match_strategy: MatchStrategy,
    match_index: int,
    case_sensitive: bool,
    optional_punct: set[str],
) -> Optional[dict]:
    """
    Match punctuation-separated phrases across adjacent OCR word rows within the same OCR line.

    Designed for cases like "my.name" where OCR may emit:
    - ["my.name"]  (single token)
    - ["my", ".", "name"]  (punct split out)
    - ["my", "name"]  (punct dropped)

    This does NOT attempt fuzzy matching; it only matches contiguous tokens on a line.
    """
    if not phrase or not phrase.strip():
        return None

    if not case_sensitive:
        def norm(s: str) -> str:
            return s.casefold()
    else:
        def norm(s: str) -> str:
            return s

    query_tokens = _tokenize_punct_phrase(phrase)
    if not query_tokens:
        return None

    # Build token-pattern variants where selected punctuation is optional (present or absent).
    # This keeps matching deterministic while covering common OCR tokenization.
    variants: list[list[str]] = [query_tokens]
    for p in list(query_tokens):
        if p in optional_punct:
            variants.append([t for t in query_tokens if t != p])

    # Deduplicate variants while preserving order.
    seen: set[tuple[str, ...]] = set()
    uniq_variants: list[list[str]] = []
    for v in variants:
        key = tuple(v)
        if key in seen:
            continue
        if not v:
            continue
        seen.add(key)
        uniq_variants.append(v)

    # Group by OCR line (block/par/line), then scan for a contiguous token match.
    line_groups: dict[tuple[int, int, int], list[dict]] = {}
    for r in rows:
        if r["conf"] < min_conf:
            continue
        key = (int(r.get("block_num", 0)), int(r.get("par_num", 0)), int(r.get("line_num", 0)))
        line_groups.setdefault(key, []).append(r)

    candidates: list[dict] = []
    for _, line_rows in line_groups.items():
        line_rows_sorted = sorted(
            line_rows, key=lambda r: (int(r.get("word_num", 0)), int(r["left"]), int(r["top"]))
        )
        line_tokens = [norm(r["text"]) for r in line_rows_sorted]

        for variant in uniq_variants:
            tokens_norm = [norm(t) for t in variant]
            if len(line_tokens) < len(tokens_norm):
                continue

            for start in range(0, len(line_tokens) - len(tokens_norm) + 1):
                window = line_tokens[start : start + len(tokens_norm)]
                if window != tokens_norm:
                    continue

                matched_rows = line_rows_sorted[start : start + len(tokens_norm)]
                left, top, width, height = _union_bbox(matched_rows)
                conf = sum(float(r["conf"]) for r in matched_rows) / max(1, len(matched_rows))
                i0 = min(int(r["i"]) for r in matched_rows)

                candidates.append(
                    {
                        "i": i0,
                        "text": phrase,  # return the original query phrase
                        "conf": float(conf),
                        "left": int(left),
                        "top": int(top),
                        "width": int(width),
                        "height": int(height),
                    }
                )

    if not candidates:
        return None

    if match_index < 0:
        raise ValueError("match_index must be >= 0.")

    if match_strategy == "first":
        ordered = sorted(candidates, key=lambda r: int(r["i"]))
        return ordered[match_index] if match_index < len(ordered) else None

    ranked = sorted(candidates, key=lambda r: (float(r["conf"]), -int(r["i"])), reverse=True)
    return ranked[match_index] if match_index < len(ranked) else None


def _select_match(
    *,
    rows: list[dict],
    word: str,
    min_conf: float,
    match_strategy: MatchStrategy,
    match_index: int,
    case_sensitive: bool,
    allow_contains: bool,
) -> Optional[dict]:
    if not case_sensitive:
        needle = word.casefold()

        def norm(s: str) -> str:
            return s.casefold()
    else:
        needle = word

        def norm(s: str) -> str:
            return s

    exact: list[dict] = []
    contains: list[dict] = []

    for r in rows:
        if r["conf"] < min_conf:
            continue
        hay = norm(r["text"])
        if hay == needle:
            exact.append(r)
        elif allow_contains and needle in hay:
            contains.append(r)

    candidates = exact or contains
    if not candidates:
        return None

    if match_index < 0:
        raise ValueError("match_index must be >= 0.")

    if match_strategy == "first":
        # Preserve OCR order, but allow selecting a later occurrence.
        return candidates[match_index] if match_index < len(candidates) else None

    # best
    ranked = sorted(candidates, key=lambda r: (r["conf"], -r["i"]), reverse=True)
    return ranked[match_index] if match_index < len(ranked) else None


def _center_of_bbox(left: int, top: int, width: int, height: int) -> Tuple[float, float]:
    return (left + width / 2.0, top + height / 2.0)


def _approx_letter_coords_within_word_bbox(
    *,
    word: str,
    letter: str,
    letter_index: int,
    bbox_left: int,
    bbox_top: int,
    bbox_width: int,
    bbox_height: int,
) -> Tuple[float, float]:
    indices = [i for i, ch in enumerate(word) if ch == letter]
    if not indices:
        raise ValueError(f"Letter {letter!r} is not in word {word!r}.")
    if letter_index < 0 or letter_index >= len(indices):
        raise ValueError(
            f"letter_index {letter_index} out of range for {letter!r} in {word!r} (found {len(indices)} occurrences)."
        )
    i = indices[letter_index]
    # Approximate: assume monospaced distribution of letters across the word bbox.
    x = bbox_left + ((i + 0.5) / max(1, len(word))) * bbox_width
    y = bbox_top + bbox_height / 2.0
    return (x, y)


def _precise_letter_coords_from_cropped_boxes(
    *,
    cropped_img,
    bbox_left: int,
    bbox_top: int,
    letter: str,
    letter_index: int,
    case_sensitive: bool,
) -> Optional[Tuple[float, float]]:
    """
    More accurate letter coordinate extraction using `image_to_boxes` on the cropped word image.

    Returns screen coords (x, y) or None if the requested letter occurrence can't be found.
    """
    try:
        boxes_str = pytesseract.image_to_boxes(cropped_img)
    except Exception:
        return None

    lines = [ln.strip() for ln in boxes_str.splitlines() if ln.strip()]
    if not lines:
        return None

    occurrences: list[Tuple[float, float]] = []
    img_h = int(getattr(cropped_img, "height", 0) or 0)
    if img_h <= 0:
        return None

    letter_norm = letter if case_sensitive else letter.casefold()

    for ln in lines:
        parts = ln.split()
        # expected: char left bottom right top page
        if len(parts) < 5:
            continue
        ch = parts[0]
        ch_norm = ch if case_sensitive else ch.casefold()
        if ch_norm != letter_norm:
            continue
        try:
            left = int(parts[1])
            bottom = int(parts[2])
            right = int(parts[3])
            top = int(parts[4])
        except Exception:
            continue

        x_local = (left + right) / 2.0
        y_local_from_bottom = (bottom + top) / 2.0
        # Convert to top-left origin within the cropped image.
        y_local = img_h - y_local_from_bottom
        occurrences.append((bbox_left + x_local, bbox_top + y_local))

    if letter_index < 0 or letter_index >= len(occurrences):
        return None
    return occurrences[letter_index]


def locate_text_match(
    word: str,
    *,
    letter: Optional[str] = None,
    letter_index: int = 0,
    debug: bool = False,
    window_title: Optional[str] = None,
    region: Optional[Region] = None,
    min_conf: float = 60.0,
    match_strategy: MatchStrategy = "best",
    match_index: int = 0,
    case_sensitive: bool = True,
    allow_contains: bool = False,
    lang: str = "eng",
    psm: Optional[int] = None,
    precise_letter: bool = False,
    tesseract_cmd: Optional[str] = None,
    tessdata_dir: Optional[str] = None,
) -> Optional[OcrMatch]:
    """
    Optimized API.\n
    - Captures only the requested window/region (or full screen fallback).\n
    - Uses word-level OCR data (single pass) with confidence filtering.\n
    - Returns structured match info (coords, bbox, confidence, etc.).\n
    """
    if not word or not word.strip():
        raise ValueError("word must be a non-empty string.")
    word = word.strip()

    if letter is not None:
        if len(letter) != 1:
            raise ValueError("letter must be a single character (or None).")

    _ensure_tesseract_configured(tesseract_cmd=tesseract_cmd, tessdata_dir=tessdata_dir)

    source_region = _normalize_region(region=region, window_title=window_title)
    img = _capture(source_region)

    config = _tesseract_config(psm=psm)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang=lang, config=config)

    rows = list(_iter_word_rows(data))
    # If the query contains whitespace, treat it as a phrase and match across adjacent
    # word tokens within the same OCR line (block/par/line grouping).
    if any(ch.isspace() for ch in word):
        chosen = _select_phrase_match(
            rows=rows,
            phrase=word,
            min_conf=min_conf,
            match_strategy=match_strategy,
            match_index=match_index,
            case_sensitive=case_sensitive,
        )
    else:
        chosen = _select_match(
            rows=rows,
            word=word,
            min_conf=min_conf,
            match_strategy=match_strategy,
            match_index=match_index,
            case_sensitive=case_sensitive,
            allow_contains=allow_contains,
        )
        # Common OCR behavior: punctuation may be split into its own token (or dropped).
        # If the exact/contains match fails and the query includes punctuation like "my.name",
        # try a line-level token match with optional punctuation tokens.
        if chosen is None and any((not ch.isalnum()) for ch in word) and not allow_contains:
            chosen = _select_punct_phrase_match(
                rows=rows,
                phrase=word,
                min_conf=min_conf,
                match_strategy=match_strategy,
                match_index=match_index,
                case_sensitive=case_sensitive,
                optional_punct={"."},
            )

    _debug_print(debug, f"source_region={source_region}")
    _debug_print(
        debug,
        f"rows={len(rows)} min_conf={min_conf} chosen={None if chosen is None else (chosen['text'], chosen['conf'])}",
    )

    if chosen is None:
        return None

    region_left, region_top, _, _ = source_region

    bbox_left = region_left + chosen["left"]
    bbox_top = region_top + chosen["top"]
    bbox_width = chosen["width"]
    bbox_height = chosen["height"]

    if letter is None:
        x, y = _center_of_bbox(bbox_left, bbox_top, bbox_width, bbox_height)
    else:
        # For letter indexing, normalize word/letter consistently with the matching mode.
        word_for_letter = word if case_sensitive else word.casefold()
        letter_for_letter = letter if case_sensitive else letter.casefold()

        if precise_letter:
            # Crop the detected word box out of the captured image and run char boxing on that.
            # The crop is in capture-image coordinates, so subtract the capture origin.
            crop_left = int(chosen["left"])
            crop_top = int(chosen["top"])
            crop_right = crop_left + int(bbox_width)
            crop_bottom = crop_top + int(bbox_height)
            cropped = img.crop((crop_left, crop_top, crop_right, crop_bottom))

            precise = _precise_letter_coords_from_cropped_boxes(
                cropped_img=cropped,
                bbox_left=bbox_left,
                bbox_top=bbox_top,
                letter=letter_for_letter,
                letter_index=letter_index,
                case_sensitive=case_sensitive,
            )
        else:
            precise = None

        if precise is not None:
            x, y = precise
        else:
            x, y = _approx_letter_coords_within_word_bbox(
                word=word_for_letter,
                letter=letter_for_letter,
                letter_index=letter_index,
                bbox_left=bbox_left,
                bbox_top=bbox_top,
                bbox_width=bbox_width,
                bbox_height=bbox_height,
            )

    return OcrMatch(
        coords=(x, y),
        bbox=(bbox_left, bbox_top, bbox_width, bbox_height),
        confidence=float(chosen["conf"]),
        matched_text=str(chosen["text"]),
        source_region=source_region,
    )

def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Find a word on the screen via OCR and return/move to its coordinates."
    )
    parser.add_argument("word", help="Text to search for (word or multi-word phrase).")
    parser.add_argument(
        "--letter",
        default=None,
        help="Optional: specific letter within the word to target.",
    )
    parser.add_argument(
        "--letter-index",
        type=int,
        default=0,
        help="Which occurrence of the letter within the word to target (0-based).",
    )
    parser.add_argument(
        "--window-title",
        default=None,
        help="Optional: window title (substring match) to restrict OCR to that window.",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Optional: 'left,top,width,height' region to restrict OCR.",
    )
    parser.add_argument(
        "--min-conf",
        type=float,
        default=60.0,
        help="Minimum OCR confidence to accept (0-100, default: 60).",
    )
    parser.add_argument(
        "--match-strategy",
        choices=["best", "first"],
        default="best",
        help="How to choose between multiple matches (default: best).",
    )
    parser.add_argument(
        "--match-index",
        type=int,
        default=0,
        help="Which match to use when multiple matches are found (0-based).",
    )
    parser.add_argument(
        "--case-insensitive",
        action="store_true",
        help="Case-insensitive word matching.",
    )
    parser.add_argument(
        "--contains",
        action="store_true",
        help="Allow substring matches (less reliable).",
    )
    parser.add_argument(
        "--lang",
        default="eng",
        help="Tesseract language (default: eng).",
    )
    parser.add_argument(
        "--psm",
        type=int,
        default=None,
        help="Optional Tesseract page segmentation mode (e.g. 6, 7, 11).",
    )
    parser.add_argument(
        "--precise-letter",
        action="store_true",
        help="If --letter is provided, attempt precise per-letter boxing within the detected word.",
    )
    parser.add_argument(
        "--tesseract-cmd",
        default=None,
        help="Override path to tesseract.exe.",
    )
    parser.add_argument(
        "--tessdata-dir",
        default=None,
        help="Override path to tessdata folder.",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move the mouse to the detected coordinates (safer than clicking).",
    )
    parser.add_argument(
        "--click",
        action="store_true",
        help="Click the detected coordinates.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.5,
        help="Mouse move duration in seconds (default: 0.5).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay before moving/clicking (seconds).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose OCR/box debugging output.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])

    word = args.word
    region = _parse_region(args.region) if args.region else None

    match = locate_text_match(
        word,
        letter=args.letter,
        letter_index=args.letter_index,
        debug=args.debug,
        window_title=args.window_title,
        region=region,
        min_conf=args.min_conf,
        match_strategy=args.match_strategy,
        match_index=args.match_index,
        case_sensitive=not args.case_insensitive,
        allow_contains=args.contains,
        lang=args.lang,
        psm=args.psm,
        precise_letter=args.precise_letter,
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
    )
    coords = None if match is None else match.coords

    if coords is None:
        sys.exit(1)

    print(f"coords: {coords}")

    if args.delay > 0:
        time.sleep(args.delay)

    if args.move or args.click:
        pyautogui.moveTo(coords[0], coords[1], duration=args.duration)

    if args.click:
        pyautogui.click()
