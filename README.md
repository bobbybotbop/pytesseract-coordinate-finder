# Pytesseract Coordinate Finder
Using PyTesseract, it locates text on the screen, and grabs the screen coordinates (x,y) of the center of the word (or individual letters *configurable*).
Doesn't do that stupid glyph thing where it makes boxes around text, it just grabs the coordinates of the text. (I made this because all I could find was how to make the glyph)

## Installation

### Install Modules

#### PyTesseract

Install required packages:
```
py -m pip install pytesseract
py -m pip install Pillow
```

#### pyautogui
Install required packages:
```
py -m pip install pyautogui
```

#### pygetwindow
Install required packages:
```
py -m pip install pygetwindow
```

### Configure PyTesseract
PyTesseract requires both the python module, and the OCR folder, so you must have the [Tesseract-OCR](<https://github.com/DiamondYTR/pytesseract-coordinate-finder/tree/main/Tesseract-OCR>) folder in the same folder as the python script.

## Usage
### UI Tester (recommended)

Run the interactive tester:

```
py ui_tester.py
```

To find coordinates using a **single input word**:

- Put your target text into the **Word** field (example: `Multiplayer` or `my.name`)
- Leave everything else blank
- Click **Run OCR**
- Read the result in the Output box:
  - `coords: (x, y)` is the screen coordinate of the match

Defaults used by the UI when you don’t change anything:

- **Case-sensitive** matching
- **Min confidence**: `60`
- **Match strategy**: `best`

### Library

The function `locate_text(word, letter=None, ...)` returns **screen coordinates** `(x, y)` for the center of the detected word (or for a specific letter).\n
\n
For more control, use `locate_text_match(...)`, which returns an `OcrMatch` containing `coords`, `bbox`, `confidence`, `matched_text`, and `source_region`.

#### Basic examples

- **Word center**:

```
locate_text("Multiplayer")
```

- **Specific letter** (first occurrence):

```
locate_text("Multiplayer", "r")
```

#### Faster + more reliable capture

By default it captures the full screen. For major performance wins, restrict OCR:\n
\n
- **Window capture** (requires `pygetwindow`):

```
locate_text_match("Multiplayer", window_title="Minecraft")
```

- **Region capture**:

```
locate_text_match("Multiplayer", region=(0, 0, 800, 600))
```

#### Matching and reliability knobs

- **Confidence threshold**: `min_conf` (default `60.0`)\n
- **Multiple matches**: use `match_strategy` (`best`/`first`) plus `match_index` (0-based)\n
- **Case-insensitive matching**: `case_sensitive=False`\n
- **Substring matching** (less reliable): `allow_contains=True`\n
- **Letter disambiguation**: `letter_index` (0-based occurrence within the word)\n
- **More accurate letter boxing**: `precise_letter=True` (slower; only runs per-letter boxing inside the matched word box)\n
\n
### CLI

`text_finder.py` can also be run directly. It prints `coords: (x, y)` and can optionally move/click.\n
\n
Examples:\n
\n
```
py text_finder.py Multiplayer --window-title Minecraft --move
```
\n
```
py text_finder.py Multiplayer --region 0,0,800,600 --min-conf 70 --match-strategy best --match-index 0
```

## Notes
This program was made in help by ChatGPT, which is why you may see occasional comments throughout the script, though in some areas I heavily modified the original content, so the comments may not always be accurate.

This is my first time using GitHub, I only made this because I know I would've killed to have this when I was originally just trying to make simple text recognition to grab the coordinates of a button on my monitor. So if this repository looks a little off, that's probably why.

I hope this code could be of help to you!




