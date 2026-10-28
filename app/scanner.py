import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import cv2
import numpy as np
import pyautogui

from avatar_detector import detect_avatar_circles
from capture import capture_screen
from ocr import recognize_text

try:
    import mss
except ImportError:
    mss = None

USERNAME_CHARS = re.compile(r"[^A-Za-z0-9._]")

# ---- speed / scrolling settings ----
OCR_WORKERS = min(8, os.cpu_count() or 4)  # set to 1 to disable parallel OCR
START_CLICKS = 10      # initial scroll step (adapts automatically)
MAX_CLICKS = 40        # upper bound for the adaptive step
GROW_HITS = 2          # grow the step when >= this many rows were already seen
END_RETRIES = 4        # unchanged screens in a row = bottom of list
INK_THRESHOLD = 40     # color difference that counts as text
LINE_GAP = 4           # blank pixel rows that separate two text lines
DEBUG_SCREENS = True   # print one line per screen (clicks, rows, hits, new)

_pool = ThreadPoolExecutor(max_workers=OCR_WORKERS)

# ---- timing (printed at the end of a scan) ----
TIMES = {"grab": 0.0, "detect": 0.0, "ocr": 0.0, "scroll_wait": 0.0}


@contextmanager
def timed(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        TIMES[name] += time.perf_counter() - start


def crop_region(image, region):
    x, y, width, height = region
    return image[y:y + height, x:x + width]


def make_grabber(region):
    """
    Returns a function that captures just the list region.
    Uses mss (fast) when available and consistent with capture_screen().
    """
    x, y, w, h = region

    def slow():
        return crop_region(capture_screen(), region)

    if mss is None:
        print("Capture: capture_screen (install 'mss' for faster capture)")
        return slow

    sct = mss.mss()

    def fast():
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # BGRA -> BGR

    try:
        a, b = fast(), slow()
        if a.shape == b.shape and float(np.mean(cv2.absdiff(a, b))) < 5:
            print("Capture: mss (fast)")
            return fast
    except Exception as exc:
        print(f"mss check failed: {exc}")

    print("Capture: mss disagreed with capture_screen (DPI?), using capture_screen")
    return slow


def get_row_boxes(circles, size, pad=4, left_gap=8):
    """
    One text box per avatar: starts just right of the circle and spans the
    circle's own vertical extent (so it never reaches neighboring rows).
    Returns [(circle, (left, top, right, bottom)), ...].
    """
    width, height = size
    boxes = []
    for cx, cy, r in circles:
        left = cx + r + left_gap
        top = max(0, cy - r - pad)
        bottom = min(height, cy + r + pad)
        right = width
        if right - left > 20 and bottom - top > 10:
            boxes.append(((cx, cy, r), (left, top, right, bottom)))
    return boxes


def find_username_line(cropped, box):
    """
    Shrink a row box to the first (top) text line only, trimmed to the
    width of the text. Returns (left, top, right, bottom) or None.
    """
    left, top, right, bottom = box
    row = cropped[top:bottom, left:right]

    bg = np.median(row.reshape(-1, 3), axis=0)
    diff = np.abs(row.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    ink = diff > INK_THRESHOLD

    ys = np.flatnonzero(ink.sum(axis=1) >= 2)
    if ys.size == 0:
        return None

    start = end = int(ys[0])
    for y in ys[1:]:
        if y - end > LINE_GAP:
            break
        end = int(y)

    cols = np.flatnonzero(ink[start:end + 1].any(axis=0))
    if cols.size == 0:
        return None

    t = max(0, start - 3)
    b = min(row.shape[0], end + 4)
    l = max(0, int(cols[0]) - 3)
    r = min(row.shape[1], int(cols[-1]) + 4)
    if b - t < 8 or r - l < 8:
        return None

    return (left + l, top + t, left + r, top + b)


def extract_username(text):
    """First token of the first non-empty line, or None if it looks wrong."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        token = USERNAME_CHARS.sub("", line.split()[0]).strip(".")

        if len(token) >= 2:
            return token.lower()
        return None

    return None


def read_rows(cropped, cache=None):
    """
    Detect avatars in `cropped` and OCR the username line beside each one.
    If `cache` (a dict) is given, rows whose crop is pixel-identical to one
    already read are not OCRed again.
    Returns a list of dicts: circle, box (the OCR crop), raw, username, cached.
    """
    height, width = cropped.shape[:2]

    with timed("detect"):
        circles = detect_avatar_circles(cropped)

    rows = []
    pending = []

    for circle, box in get_row_boxes(circles, (width, height)):
        line_box = find_username_line(cropped, box)
        if line_box is None:
            continue

        left, top, right, bottom = line_box
        crop = cropped[top:bottom, left:right]
        key = hash(crop.tobytes())

        row = {"circle": circle, "box": line_box, "raw": None,
               "username": None, "key": key, "cached": False}
        rows.append(row)

        if cache is not None and key in cache:
            row["username"] = cache[key]
            row["cached"] = True
        else:
            pending.append((row, crop))

    if pending:
        crops = [crop for _, crop in pending]
        with timed("ocr"):
            if OCR_WORKERS > 1 and len(crops) > 1:
                texts = list(_pool.map(recognize_text, crops))
            else:
                texts = [recognize_text(crop) for crop in crops]

        for (row, _), text in zip(pending, texts):
            row["raw"] = text
            row["username"] = extract_username(text)
            if cache is not None and row["username"]:
                cache[row["key"]] = row["username"]

    return rows


def scan_visible_rows(image, region):
    """Returns the usernames found in a single screenshot."""
    rows = read_rows(crop_region(image, region))

    if not rows:
        print("No avatar circles detected.")
        return []

    usernames = [row["username"] for row in rows if row["username"]]
    for name in usernames:
        print(f"Detected: {name}")

    return list(dict.fromkeys(usernames))


def _delta(a, b):
    """Mean pixel difference between two frames (every 2nd pixel, for speed)."""
    return float(np.mean(cv2.absdiff(a[::2, ::2], b[::2, ::2])))


def grab_settled(grab, should_stop, before=None,
                 start_wait=0.15, max_wait=0.8, poll=0.01):
    """
    Capture once the scroll has finished. Pass the pre-scroll frame as
    `before` so a scroll that hasn't started yet isn't read as 'settled'.
    """
    t0 = time.perf_counter()
    with timed("grab"):
        previous = grab()
    started = before is None

    while not should_stop():
        elapsed = time.perf_counter() - t0
        if not started:
            if _delta(before, previous) >= 1.0:
                started = True
            elif elapsed > start_wait:
                return previous          # nothing moved: bottom, or still loading
        if started and elapsed > max_wait:
            return previous

        with timed("scroll_wait"):
            time.sleep(poll)
        with timed("grab"):
            current = grab()
        if started and _delta(previous, current) < 0.3:
            return current
        previous = current

    return previous


def scan_entire_list(region, should_stop, progress_callback):
    """Scroll through the list and collect usernames."""
    pyautogui.PAUSE = 0  # default adds 0.1s after every pyautogui call

    for key in TIMES:
        TIMES[key] = 0.0

    all_usernames = []
    seen = set()
    cache = {}
    screen_count = 0
    clicks = START_CLICKS
    ceiling = MAX_CLICKS
    started = time.perf_counter()

    x, y, width, height = region
    grab = make_grabber(region)

    # Put the cursor over the scrollable list.
    pyautogui.moveTo(x + width // 2, y + height // 2)

    cropped = grab_settled(grab, should_stop)

    while not should_stop():
        rows = read_rows(cropped, cache)

        # A row counts as a "hit" if we've already collected it, which tells
        # us how much this screen overlaps the previous ones.
        count_before = len(all_usernames)
        hits = 0
        for row in rows:
            name = row["username"]
            seen_before = bool(name) and name in seen
            if row["cached"] or seen_before:
                hits += 1
            if name and not seen_before:
                seen.add(name)
                all_usernames.append(name)

        screen_count += 1
        progress_callback(
            f"Screen {screen_count} | "
            f"{len(all_usernames)} unique usernames"
        )
        if DEBUG_SCREENS:
            print(
                f"screen {screen_count}: clicks={clicks} rows={len(rows)} "
                f"hits={hits} new={len(all_usernames) - count_before} "
                f"cached={sum(r['cached'] for r in rows)} "
                f"no_name={sum(1 for r in rows if not r['username'])}"
            )

        if should_stop():
            break

        previous = cropped

        if screen_count > 1 and rows and hits == 0 and clicks > 1:
            # No overlap: we may have skipped rows. Back up part of the way
            # and use a smaller step from now on.
            new_clicks = max(1, clicks // 2)
            pyautogui.scroll(clicks - new_clicks)  # positive = up
            ceiling = max(new_clicks, clicks - 1)
            clicks = new_clicks
        else:
            # One overlapping row already proves nothing was skipped, so
            # grow the step whenever there is plenty of overlap.
            if hits >= GROW_HITS:
                clicks = min(ceiling, clicks * 2)
            pyautogui.scroll(-clicks)

        # If nothing changed, the list may still be loading more rows, so
        # retry a few times before calling it the end.
        for _ in range(END_RETRIES):
            cropped = grab_settled(grab, should_stop, before=previous)
            if float(np.mean(cv2.absdiff(previous, cropped))) >= 1.0:
                break
            if should_stop():
                break
            pyautogui.scroll(-1)  # nudge to trigger lazy loading
            with timed("scroll_wait"):
                time.sleep(0.25)
        else:
            progress_callback("Reached the bottom of the list.")
            break

    total = time.perf_counter() - started
    print(
        f"\nDone: {len(all_usernames)} usernames, {screen_count} screens, "
        f"{total:.1f}s total ({len(all_usernames) / max(total, 0.01):.1f}/s)"
    )
    print("Time spent: " + ", ".join(f"{k} {v:.1f}s" for k, v in TIMES.items()))

    return all_usernames, should_stop(), screen_count