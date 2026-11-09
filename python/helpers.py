"""Shared drawing helpers for the paper-translation pipeline.

Extracted from the earlier per-version scripts: one copy of the text metrics,
glyph erasing and layout primitives, used by the renderer only.
"""

import functools
import pathlib
import re

import numpy as np
from PIL import ImageFont
from scipy import ndimage

BODY_INK = (25, 25, 25)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"


@functools.lru_cache(maxsize=64)
def font_of(size, bold=False):
    """Cached: rebuilding a TrueType face per draw call was a top cost."""
    size = max(5, int(size))
    for path in ((FONT_BOLD, FONT_REG) if bold else (FONT_REG, FONT_BOLD)):
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    raise SystemExit("no CJK font available")


def wrap_text(draw, text, font, max_width):
    """Balanced wrap using binary search instead of per-glyph measurement.

    The old loop measured a growing prefix for every character, which is
    O(n) font-metric calls per line and dominated the build time on long
    paragraphs. Binary search makes it O(log n) per line.
    """
    text = " ".join(str(text).split())
    if not text:
        return []
    length = draw.textlength(text, font=font)
    if length <= max_width:
        return [text]
    line_count = int(-(-length // max_width))
    target = length / line_count

    def fits(chunk):
        return draw.textlength(chunk, font=font) <= target + 1e-6

    lines = []
    start = 0
    total = len(text)
    while start < total:
        lo, hi = start + 1, total
        best = start + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if fits(text[start:mid]):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best < total:
            # prefer a natural break if one is close behind the limit
            window = text[start:best]
            for mark in (" ", "、", "，", "；", "。", "：", ")", "+"):
                pos = window.rfind(mark)
                if pos > len(window) * 0.55:
                    best = start + pos + 1
                    break
        lines.append(text[start:best].strip())
        start = best
    return [line for line in lines if line]


def erase_glyphs(arr, box, threshold=40, grow=2):
    """Replace glyph pixels with the local background; returns that colour."""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > threshold
    if ink.sum() == 0:
        return None
    colour = np.median(region[~ink], axis=0).astype(np.uint8)
    region[ndimage.binary_dilation(ink, iterations=grow)] = colour
    return tuple(int(v) for v in colour)


def draw_single_line(draw, box, text, ink):
    """One line, shrunk to the cell width: cells can never overlap vertically."""
    text = " ".join(str(text).split())
    if not text:
        return None
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width < 4 or height < 4:
        return None
    size = max(6, int(height * 0.80))
    size = min(size, 17)          # never let a merged block blow the glyph up
    while size > 5 and draw.textlength(text, font=font_of(size)) > width:
        size -= 1
    font = font_of(size)
    draw.text((x0, y0 + max(0, (height - size * 1.2) / 2)), text, font=font, fill=ink)
    return size


def draw_text(draw, box, text, ref_size, ink, min_size=7):
    """Wrapped text that shrinks to its box, falling back to a single line."""
    text = " ".join(str(text).split())
    if not text:
        return None
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width < 5 or height < 5:
        return None
    size = max(min_size, int(ref_size * 1.15))
    while size >= min_size:
        font = font_of(size)
        lines = wrap_text(draw, text, font, width)
        if len(lines) * size * 1.28 <= height + 2:
            break
        size -= 1
    font = font_of(max(size, min_size))
    lines = wrap_text(draw, text, font, width)
    line_h = font.size * 1.28
    if len(lines) * line_h > height + 3:
        return draw_single_line(draw, box, text, ink)
    y = y0 + max(0, (height - len(lines) * line_h) / 2)
    for line in lines:
        draw.text((x0, y), line, font=font, fill=ink)
        y += line_h
    return font.size


def should_skip(source, translated):
    """Leave original pixels alone when nothing was really translated."""
    source = " ".join(str(source).split())
    translated = " ".join(str(translated).split())
    if source == translated:
        return True
    if CJK_RE.search(translated):
        return False
    shorter = min(len(source), len(translated)) or 1
    return max(len(source), len(translated)) / shorter < 1.6
