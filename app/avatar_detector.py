import cv2
import numpy as np


# ---------- helpers ----------

def _background(image):
    return np.median(image.reshape(-1, 3), axis=0)


def _diff_map(image, bg):
    return np.abs(image.astype(np.int16) - bg.astype(np.int16)).max(axis=2)


def _blob_mask(diff, threshold, close_size):
    mask = (diff > threshold).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def _evaluate_contour(contour, width, height, min_d, max_d):
    """Return (cx, cy, r, quality) if the contour is a convincing circle."""
    x, y, w, h = cv2.boundingRect(contour)
    if not (min_d <= w <= max_d and min_d <= h <= max_d):
        return None
    if not (0.85 <= w / h <= 1.18):
        return None
    if x <= 0 or y <= 0 or x + w >= width or y + h >= height:
        return None

    (cx, cy), r = cv2.minEnclosingCircle(contour)
    if r <= 0:
        return None

    # Fill: how much of the enclosing circle the blob covers.
    fill = cv2.contourArea(contour) / (np.pi * r * r)

    # Radial deviation: how constant the distance from the center is.
    pts = contour.reshape(-1, 2).astype(np.float32)
    dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    deviation = dist.std() / r

    if fill < 0.80 or deviation > 0.08:
        return None

    quality = fill * (1.0 - deviation)
    return cx, cy, r, quality


def _ring_score(diff, cx, cy, r, edge_thr, samples=90):
    """
    Fraction of the perimeter where the pixel just inside the edge differs
    from the background and the pixel just outside matches it.
    """
    h, w = diff.shape
    angles = np.linspace(0, 2 * np.pi, samples, endpoint=False)
    cos, sin = np.cos(angles), np.sin(angles)

    def sample(radius):
        xs = np.round(cx + radius * cos).astype(int)
        ys = np.round(cy + radius * sin).astype(int)
        ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        out = np.zeros(samples, dtype=np.int16)
        out[ok] = diff[ys[ok], xs[ok]]
        return out, ok

    inner, ok_in = sample(r - 2)
    outer, ok_out = sample(r + 4)
    if not (ok_in.all() and ok_out.all()):
        return 0.0  # circle would leave the region

    hit = (inner > edge_thr) & (outer <= edge_thr)
    return float(hit.mean())


# ---------- main detector ----------

def detect_avatar_circles(
    image,
    min_diameter=30,
    max_diameter=120,
    thresholds=(4, 7, 11, 16, 24),
    close_size=7,
    recover_missing=True,
    recover_min_score=0.6,
):
    """
    Detect circular profile pictures.
    Returns [(center_x, center_y, radius), ...] relative to `image`, top to bottom.
    """
    height, width = image.shape[:2]
    bg = _background(image)
    diff = _diff_map(image, bg)

    # 1. Multi-threshold sweep.
    candidates = []  # (quality, cx, cy, r)
    for thr in thresholds:
        mask = _blob_mask(diff, thr, close_size)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            result = _evaluate_contour(contour, width, height, min_diameter, max_diameter)
            if result is not None:
                cx, cy, r, q = result
                candidates.append((q, cx, cy, r))

    # 2. Merge duplicates: best quality wins, larger radius breaks ties.
    candidates.sort(key=lambda c: (round(c[0], 2), c[3]), reverse=True)
    kept = []
    for q, cx, cy, r in candidates:
        if all(np.hypot(cx - kx, cy - ky) > 0.5 * max(r, kr) for _, kx, ky, kr in kept):
            kept.append((q, cx, cy, r))

    circles = [(cx, cy, r) for _, cx, cy, r in kept]

    # 3. Layout consensus: same column, same size.
    if len(circles) >= 3:
        xs = np.array([c[0] for c in circles])
        bins = np.round(xs / 8).astype(int)
        mode_bin = np.bincount(bins - bins.min()).argmax() + bins.min()
        circles = [c for c, b in zip(circles, bins) if abs(b - mode_bin) <= 1]

        median_r = np.median([c[2] for c in circles])
        circles = [c for c in circles if abs(c[2] - median_r) <= 0.2 * median_r]

    circles.sort(key=lambda c: c[1])

    # 4. Recover avatars the segmentation missed (e.g. faint story rings).
    if recover_missing and len(circles) >= 2:
        circles = _recover_missing(circles, diff, height, edge_thr=4,
                                   min_score=recover_min_score)

    return [(int(round(cx)), int(round(cy)), int(round(r))) for cx, cy, r in circles]


def _recover_missing(circles, diff, height, edge_thr, min_score):
    cx_col = float(np.median([c[0] for c in circles]))
    r = float(np.median([c[2] for c in circles]))
    ys = sorted(c[1] for c in circles)
    pitch = float(np.median(np.diff(ys)))
    if pitch < 1.5 * r:
        return circles  # spacing looks wrong, don't guess

    # Anchor the expected row positions on the first confident detection.
    anchor = ys[0]
    first_k = -int(anchor // pitch)
    last_k = int((height - anchor) // pitch)

    result = list(circles)
    for k in range(first_k, last_k + 1):
        expected_y = anchor + k * pitch
        if expected_y - r < 0 or expected_y + r >= height:
            continue
        if any(abs(expected_y - c[1]) < 0.5 * pitch for c in result):
            continue  # already have this row

        best = None
        for dy in range(-int(0.3 * pitch), int(0.3 * pitch) + 1, 2):
            for dx in (-3, -2, -1, 0, 1, 2, 3):
                for dr in (-2, -1, 0, 1, 2):
                    score = _ring_score(diff, cx_col + dx, expected_y + dy,
                                        r + dr, edge_thr)
                    if best is None or score > best[0]:
                        best = (score, cx_col + dx, expected_y + dy, r + dr)

        if best and best[0] >= min_score:
            result.append((best[1], best[2], best[3]))

    result.sort(key=lambda c: c[1])
    return result


def draw_avatar_circles(image, circles):
    result = image.copy()
    for cx, cy, r in circles:
        cv2.circle(result, (cx, cy), r, (0, 255, 0), 2)
        cv2.circle(result, (cx, cy), 3, (0, 0, 255), -1)
    return result