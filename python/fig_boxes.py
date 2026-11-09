"""Detect text elements inside a figure and emit a numbered overlay.

Two strategies:
  1. solid-colour containers (flowcharts) -> one box per container
  2. plain background (charts/tables-as-image) -> text-line boxes

Outputs, per figure, an overlay PNG with every box numbered, plus a JSON map of
box geometry in the *figure image's* pixel space.
"""

import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

FONT = r"C:\Windows\Fonts\msyhbd.ttc"


def containers(arr):
    quant = (arr // 24) * 24
    flat = quant.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1][:14]
    total = arr.shape[0] * arr.shape[1]
    found = []
    for idx in order:
        colour = colours[idx]
        if counts[idx] < total * 0.008:
            continue
        mask = np.all(np.abs(arr.astype(np.int16) - colour.astype(np.int16)) <= 22, axis=2)
        labels, number = ndimage.label(mask)
        for label in range(1, number + 1):
            region = labels == label
            area = int(region.sum())
            if area < 2500 or area > total * 0.55:
                continue
            ys, xs = np.where(region)
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            if (x1 - x0) < 45 or (y1 - y0) < 18:
                continue
            if area / ((x1 - x0) * (y1 - y0)) < 0.55:
                continue
            found.append([x0, y0, x1, y1])
    # drop boxes almost fully contained in a larger one
    found.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    keep = []
    for box in found:
        inside = any(box[0] >= k[0] - 3 and box[1] >= k[1] - 3
                     and box[2] <= k[2] + 3 and box[3] <= k[3] + 3 for k in keep)
        if not inside:
            keep.append(box)
    return keep


def text_lines(arr):
    grey = arr.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > 45
    rows = ink.sum(axis=1)
    bands, start = [], None
    for y, value in enumerate(rows):
        if value >= 6 and start is None:
            start = y
        elif value < 6 and start is not None:
            if y - start >= 7:
                bands.append((start, y))
            start = None
    if start is not None and len(rows) - start >= 7:
        bands.append((start, len(rows)))
    boxes = []
    for y0, y1 in bands:
        cols = ink[y0:y1].sum(axis=0)
        xs = np.where(cols >= 1)[0]
        if len(xs) == 0:
            continue
        # split a band into runs separated by wide gaps
        segments, run_start = [], xs[0]
        for i in range(1, len(xs)):
            if xs[i] - xs[i - 1] > 25:
                segments.append((run_start, xs[i - 1] + 1))
                run_start = xs[i]
        segments.append((run_start, xs[-1] + 1))
        for x0, x1 in segments:
            if x1 - x0 < 12 or y1 - y0 < 7:
                continue
            boxes.append([int(x0), int(y0), int(x1), int(y1)])
    return boxes


def main() -> int:
    figdir = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    result = {}

    for path in sorted(figdir.glob("fig_p*.png")):
        image = Image.open(path).convert("RGB")
        arr = np.asarray(image)
        boxes = containers(arr)
        if len(boxes) < 3:
            boxes = text_lines(arr)
        boxes.sort(key=lambda b: (round(b[1] / 25), b[0]))

        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.truetype(FONT, 26)
        for index, (x0, y0, x1, y1) in enumerate(boxes, start=1):
            draw.rectangle([x0, y0, x1, y1], outline=(230, 0, 0), width=3)
            label = str(index)
            tx = max(2, x0 - 2)
            ty = max(2, y0 - 30)
            draw.rectangle([tx - 2, ty - 2, tx + 14 * len(label) + 6, ty + 30],
                           fill=(255, 255, 255))
            draw.text((tx + 2, ty), label, font=font, fill=(200, 0, 0))

        overlay.save(outdir / path.name)
        result[path.name] = boxes
        print(f"{path.name}: boxes={len(boxes)}")

    (outdir / "boxes.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
