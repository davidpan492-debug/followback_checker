# Avatar Username Scanner

Reads usernames from a scrolling list on your screen (such as an Instagram followers or following list open in a browser). It finds each circular profile picture, reads the username next to it with OCR, scrolls down, and repeats until it reaches the bottom of the list. Duplicates are removed along the way.

It works on screenshots only. It does not log in to anything or talk to any website, so it only sees what is visible on your screen.

## How it works

1. **Capture**: grabs just the list region of the screen (fast `mss` capture when available).
2. **Detect avatars**: finds circular profile pictures by comparing the image against the flat background color, then filtering blobs by size, squareness and how circular they are. Faint story rings are recovered by checking where a missing row should be.
3. **Read usernames**: crops the first line of text beside each avatar and runs OCR on it. Rows that look pixel-identical to one already read are not OCR'd again.
4. **Scroll and settle**: scrolls the list, waits until the picture stops moving, then repeats. The scroll step grows when screens overlap a lot and shrinks if a screen has no overlap (which means rows may have been skipped).
5. **Finish**: stops when the screen no longer changes after several retries, then prints the totals and a timing breakdown.

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point. Turns on DPI awareness, then starts the GUI. |
| `gui.py` | The app window (`run_app`). |
| `scanner.py` | Scan loop: capture, row reading, scrolling, de-duplication, timing. Contains `scan_entire_list`. |
| `avatar_detector.py` | Circle detection (`detect_avatar_circles`, `draw_avatar_circles`). |
| `capture.py` | `capture_screen()`, the fallback full-screen capture. |
| `ocr.py` | `recognize_text()`, the OCR call used on each username crop. |

If your scan loop lives in a file with a different name, keep that name. Only the contents matter.

## Requirements

- Windows (the DPI handling in `main.py` is Windows-specific)
- Python 3
- Python packages: `opencv-python`, `numpy`, `pyautogui`, and optionally `mss` (strongly recommended for speed)
- Whatever OCR engine `ocr.py` uses, installed and working

```
pip install opencv-python numpy pyautogui mss
```

## Running

```
python main.py
```

Then, in the app:

1. Open the list in your browser so the avatars and usernames are visible.
2. Select the region of the screen that covers the list (avatars and names only, no page header or other content).
3. Start the scan and leave the mouse alone while it runs. The scanner moves the cursor over the list and scrolls it.

## Display scaling (important on Windows)

`main.py` makes the program DPI-aware before anything else loads, so screen capture, the mouse, and the selected region all use the same physical pixels. This matters if your display is scaled above 100%. Keep those lines at the top of `main.py`, above `from gui import run_app`.

When a scan starts, the console prints one of these:

- `Capture: mss (fast)`: the fast path is working.
- `Capture: mss disagreed with capture_screen (DPI?)`: it fell back to the slow capture. Check that the DPI lines in `main.py` are still first.
- `Capture: capture_screen (install 'mss' ...)`: `mss` isn't installed.

## Settings

Edit the constants at the top of `scanner.py`:

| Setting | Meaning |
|---|---|
| `START_CLICKS` | Initial scroll step, in mouse-wheel clicks. It adapts as the scan runs. |
| `MAX_CLICKS` | Upper limit for the adaptive step. |
| `GROW_HITS` | How many already-seen rows a screen needs before the step grows. |
| `END_RETRIES` | How many unchanged screens in a row count as the bottom of the list. |
| `OCR_WORKERS` | Parallel OCR threads. Set to `1` to turn off parallel OCR. |
| `INK_THRESHOLD` | How different from the background a pixel must be to count as text. |
| `LINE_GAP` | Blank pixel rows that separate two lines of text. |
| `DEBUG_SCREENS` | Prints one line per screen: step size, rows found, overlap, new names. |

Avatar detection settings (`min_diameter`, `max_diameter`, `thresholds`, and so on) are the arguments of `detect_avatar_circles` in `avatar_detector.py`.

## Output

When a scan finishes, the console shows the totals and where the time went:

```
Done: 33 usernames, 82 screens, 30.7s total (1.1/s)
Time spent: grab 9.6s, detect 2.7s, ocr 3.0s, scroll_wait 14.8s
```

The per-screen debug lines look like this:

```
screen 7: clicks=20 rows=5 hits=1 new=4 cached=1 no_name=0
```

- `rows`: avatars detected on that screen
- `hits`: rows already seen on earlier screens (the overlap)
- `new`: usernames added by this screen
- `no_name`: rows where OCR returned nothing usable

## Speeding it up

- **Turn off smooth scrolling in your browser.** In Chrome or Edge, open `chrome://flags` (or `edge://flags`), search for "smooth scrolling", set it to Disabled, and restart the browser. Scrolling then jumps instantly instead of animating, which removes most of the wait per screen.
- **Check the `Capture:` line** (see above). The fast path is much quicker than the fallback.
- **Use the debug lines to tune the step.** Many screens with `new=0` or `new=1` means the scroll step is too small. If you see `hits=0` on many screens, the step is too large (or OCR is failing on those rows), and the scanner will back off on its own.

## Troubleshooting

- **Avatars missing or wrong ones detected**: use the region selection to exclude page headers and other content. Check that your avatar diameter falls between `min_diameter` and `max_diameter`. On a 150% scaled display, avatars are roughly 60 to 70 px across.
- **Usernames come out garbled or empty**: check `no_name` in the debug lines. If it is often above 0, the OCR crop is probably off or the text is low contrast. Adjust `INK_THRESHOLD`.
- **It stops early**: the list may be lazy-loading. Raise `END_RETRIES`.
- **It skips people**: lower `START_CLICKS` and `MAX_CLICKS`. A skipped stretch shows up as a screen with `hits=0`.
- **The scroll doesn't move the list**: the cursor must be over the list. The scanner moves it to the center of the selected region, so make sure that point is inside the scrollable area.

## Notes

Use this on lists you are entitled to view, such as your own account's followers. Automated collection can go against a site's terms of use, so check them before using this on anything beyond personal use.
