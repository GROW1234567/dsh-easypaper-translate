"""Renderer for the paper-translation pipeline.

Composes the bilingual PDF: odd pages are the untouched original pages, even
pages carry the Chinese re-typeset output. Order of painting is
figures -> tables -> body text so nothing is covered after it is placed.
"""

import io
import json
import pathlib
import re
import sys

import numpy as np
import pymupdf
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from helpers import (BODY_INK, draw_single_line, draw_text,  # noqa: E402
                     erase_glyphs, font_of, should_skip, wrap_text)

GRID_RULE = (60, 60, 60)
DPI = 150
SCALE = DPI / 72.0

SANHAO_PT = 16.0          # Chinese SanHao (16 pt) cap for figure labels
MAX_FIG_PX_AT_150 = SANHAO_PT * 150 / 72.0   # ~33 px at 150 dpi
MIN_FIG_PX_AT_150 = 11.0                      # below this the glyph turns to mush


def set_dpi(dpi):
    global DPI, SCALE
    DPI = int(dpi)
    SCALE = DPI / 72.0


def fig_limits():
    factor = DPI / 150.0
    return MAX_FIG_PX_AT_150 * factor, MIN_FIG_PX_AT_150 * factor


HEADER_MAP = [
    ("Journal of Cleaner Production", "《清洁生产杂志》"),
    ("Contents lists available at ScienceDirect", "目录可在 ScienceDirect 获取"),
    ("journal homepage:", "期刊主页："),
    ("et al.", "等"),
]


def translate_header(text):
    out = " ".join(str(text).split())
    for source, target in HEADER_MAP:
        out = out.replace(source, target)
    return out


def draw_outlined(draw, box, text, ref_size, ink, min_size):
    """Draw Chinese with a stroke in the inverted colour for contrast."""
    text = " ".join(str(text).split())
    if not text:
        return None
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width < 5 or height < 5:
        return None
    size = int(max(min_size, min(ref_size, height)))
    while size > min_size:
        font = font_of(size)
        lines = wrap_text(draw, text, font, width)
        # a single tight line box is shorter than 1.24 * font size; allow a
        # modest vertical overrun rather than dropping the label entirely
        if len(lines) * size * 1.24 <= height * 1.45 + 2:
            break
        size -= 1
    font = font_of(max(size, int(min_size)))
    lines = wrap_text(draw, text, font, width)
    line_h = font.size * 1.24
    if len(lines) * line_h > height * 1.8:
        return None                      # cannot fit legibly: leave the original
    stroke = (255, 255, 255) if sum(ink) < 400 else (20, 20, 20)
    y = y0 + max(0, (height - len(lines) * line_h) / 2)
    for line in lines:
        draw.text((x0, y), line, font=font, fill=ink,
                  stroke_width=2, stroke_fill=stroke)
        y += line_h
    return font.size


def _as_map(payload):
    """Accept {"b01": "..."} or [{"id": "b01", "zh": "..."}]."""
    if isinstance(payload, dict):
        return {str(k): v for k, v in payload.items() if isinstance(v, str)}
    if isinstance(payload, list):
        result = {}
        for item in payload:
            if isinstance(item, dict):
                key = item.get("id") or item.get("key")
                value = item.get("zh") or item.get("text") or item.get("value")
                if isinstance(key, str) and isinstance(value, str):
                    result[key] = value
        return result
    return {}


def load_all(work):
    zh = {}
    for folder in ("zh", "zh2", "zh3", "zh4"):
        for path in sorted((work / folder).glob("p*.json")):
            zh.setdefault(int(path.stem[1:]), {}).update(
                _as_map(json.loads(path.read_text(encoding="utf-8"))))
    fig_map = {}
    for path in sorted((work / "figs").glob("zh_map_*.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if isinstance(value, dict) and "boxes" in value:
                fig_map[key] = value
    skip_figs = set()
    spath = work / "figs" / "skip.json"
    if spath.exists():
        skip_figs = set(json.loads(spath.read_text(encoding="utf-8")))
    fig_boxes = {}
    bpath = work / "figs" / "overlay" / "boxes.json"
    if bpath.exists():
        fig_boxes = json.loads(bpath.read_text(encoding="utf-8"))
    tables = []
    tpath = work / "tables" / "tables.json"
    if tpath.exists():
        tables = json.loads(tpath.read_text(encoding="utf-8"))
    matrices = {}
    mpath = work / "tables" / "matrices.json"
    if mpath.exists():
        matrices = json.loads(mpath.read_text(encoding="utf-8"))
    return zh, fig_map, fig_boxes, tables, matrices, skip_figs


def column_widths(header, rows, total_width):
    count = len(header)
    if count == 0:
        return []
    weights = []
    for ci in range(count):
        longest = len(str(header[ci]))
        for row in rows:
            if ci < len(row):
                longest = max(longest, len(str(row[ci])))
        weights.append(max(4, min(longest, 40)))
    total = sum(weights)
    widths = [max(46.0, total_width * w / total) for w in weights]
    factor = total_width / sum(widths)
    return [w * factor for w in widths]


_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def wrap_rows(text, size, width):
    return wrap_text(_PROBE, text, font_of(size), max(10, width))


def layout_table(header, rows, widths, size):
    pad = 5
    line_h = size * 1.3
    heights, cells = [], []
    for row in rows:
        row_cells, need = [], line_h + pad
        for ci, width in enumerate(widths):
            text = " ".join(str(row[ci]).split()) if ci < len(row) else ""
            lines = wrap_rows(text, size, width - pad * 2)
            row_cells.append(lines)
            need = max(need, len(lines) * line_h + pad)
        heights.append(need)
        cells.append(row_cells)
    header_lines, header_h = [], line_h + pad
    for ci, width in enumerate(widths):
        lines = wrap_rows(str(header[ci]), size, width - pad * 2)
        header_lines.append(lines)
        header_h = max(header_h, len(lines) * line_h + pad)
    return cells, heights, header_lines, header_h


def draw_three_line(draw, x0, y, widths, header_lines, header_h,
                    cells, heights, size, ink=BODY_INK):
    total_w = sum(widths)
    line_h = size * 1.3
    pad = 5
    draw.line([(x0, y), (x0 + total_w, y)], fill=GRID_RULE, width=2)
    y += 2
    x = x0
    for ci, width in enumerate(widths):
        ty = y + pad
        font = font_of(size, bold=True)
        for line in header_lines[ci]:
            draw.text((x + pad, ty), line, font=font, fill=ink)
            ty += line_h
        x += width
    y += header_h
    draw.line([(x0, y), (x0 + total_w, y)], fill=GRID_RULE, width=1)

    for ri, height in enumerate(heights):
        row_cells = cells[ri]
        texts = [" ".join(" ".join(c).split()) for c in row_cells]
        merged = bool(texts) and len(set(t for t in texts if t)) == 1 and texts[0]
        x = x0
        for ci, width in enumerate(widths):
            ty = y + pad
            font = font_of(size, bold=merged)
            for line in row_cells[ci]:
                draw.text((x + pad, ty), line, font=font, fill=ink)
                ty += line_h
            x += width
            if merged:
                break
        y += height
    draw.line([(x0, y), (x0 + total_w, y)], fill=GRID_RULE, width=2)
    return y


def paginate(header, rows, widths, size, first_limit, later_limit):
    pages, remaining, limit = [], list(rows), first_limit
    while remaining:
        cells, heights, hlines, hh = layout_table(header, remaining, widths, size)
        used, take = hh + 2, 0
        for height in heights:
            if used + height > limit:
                break
            used += height
            take += 1
        take = max(1, take)
        chunk = remaining[:take]
        c2, h2, hl2, hh2 = layout_table(header, chunk, widths, size)
        pages.append((chunk, c2, h2, hl2, hh2))
        remaining = remaining[take:]
        limit = later_limit
    return pages


def ink_extent(arr, box, pad=6, threshold=40):
    """Outermost ink of a region plus the local background colour."""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(arr.shape[1], x1 + pad), min(arr.shape[0], y1 + pad)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None, None
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > threshold
    if ink.sum() < 4:
        return None, None
    ys, xs = np.where(ink)
    colour = np.median(region[~ink], axis=0).astype(np.uint8)
    return ([x0 + int(xs.min()), y0 + int(ys.min()),
             x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1],
            tuple(int(v) for v in colour))


def cover_ink(arr, box, grow=3):
    """Flood the ink extent with its own background colour.

    Erasing by PDF block box leaves whatever glyphs sit outside that box
    (formula runs, table cells), which is what showed through the Chinese.
    Returns (draw_box, background) or (None, None).
    """
    extent, background = ink_extent(arr, box)
    if extent is None:
        return None, None
    x0, y0, x1, y1 = extent
    x0, y0 = max(0, x0 - grow), max(0, y0 - grow)
    x1, y1 = min(arr.shape[1], x1 + grow), min(arr.shape[0], y1 + grow)
    arr[y0:y1, x0:x1] = background
    return [x0, y0, x1, y1], background


def ink_line_height(arr, box):
    """Median height of the text lines already inside a box.

    Matching the original line height keeps figure labels the size they were
    instead of inflating them to the SanHao cap.
    """
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > 40
    counts = ink.sum(axis=1)
    bands, start = [], None
    for y, value in enumerate(counts):
        if value >= 3 and start is None:
            start = y
        elif value < 3 and start is not None:
            if y - start >= 5:
                bands.append(y - start)
            start = None
    if start is not None and len(counts) - start >= 5:
        bands.append(len(counts) - start)
    return float(np.median(bands)) if bands else None


def has_graphic_strokes(arr, box):
    """True when the box holds a curve/bar rather than plain text.

    Text glyphs are small islands; a plotted line or a filled bar is one long
    connected run. Painting the box background over such a run would erase the
    chart, so those boxes are left untouched.
    """
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    inset = 4          # the box border itself is a long stroke; ignore it
    x0, y0 = max(0, x0 + inset), max(0, y0 + inset)
    x1, y1 = min(arr.shape[1], x1 - inset), min(arr.shape[0], y1 - inset)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return False
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > 40
    if ink.sum() < 20:
        return False
    labels, count = ndimage.label(ink)
    if count == 0:
        return False
    for index in range(1, count + 1):
        ys, xs = np.where(labels == index)
        if len(xs) < 40:
            continue
        width = xs.max() - xs.min()
        height = ys.max() - ys.min()
        if width > (x1 - x0) * 0.55 or height > (y1 - y0) * 0.55:
            return True
    return False


def ink_line_count(arr, box):
    """How many distinct text lines sit inside a box."""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 0
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    # dark glyphs on white / coloured fills: a fixed luminance cut survives the
    # coloured container bars where a median-background test does not
    counts = (grey < 120).sum(axis=1)
    bands, start = 0, None
    for y, value in enumerate(counts):
        if value >= 3 and start is None:
            start = y
        elif value < 3 and start is not None:
            if y - start >= 5:
                bands += 1
            start = None
    if start is not None and len(counts) - start >= 5:
        bands += 1
    return bands


def table_columns(claimed, count, total_width):
    """Column widths taken from the original cells' own ink extents."""
    if count <= 0 or not claimed:
        return None
    starts = sorted({round(b["bbox"][0]) for b in claimed})
    clusters = []
    for value in starts:
        if clusters and value - clusters[-1][-1] <= 8:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    if len(clusters) != count:
        return None
    widths = []
    for cluster in clusters:
        left = min(cluster)
        right = max(b["bbox"][2] for b in claimed
                    if abs(b["bbox"][0] - left) <= 8)
        widths.append(max(30.0, float(right - left)))
    factor = total_width / sum(widths)
    return [w * factor for w in widths]


def tighten_box(arr, box, pad=1):
    """Trim a block box down to the outermost ink pixels.

    PDF block boxes and formula fragments often overlap while their actual
    glyphs do not; using the ink extents stops Chinese from being placed on
    top of a neighbouring element and removes dead whitespace.
    """
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return box
    region = arr[y0:y1, x0:x1]
    grey = region.mean(axis=2)
    background = float(np.median(grey))
    ink = np.abs(grey - background) > 40
    if ink.sum() < 4:
        return box
    ys, xs = np.where(ink)
    return [x0 + xs.min() - pad, y0 + ys.min() - pad,
            x0 + xs.max() + 1 + pad, y0 + ys.max() + 1 + pad]


def cell_region(blocks, crop_bbox, row_count):
    """Claim exactly the rows the matrix is going to re-author.

    The matrix tells us how many rows the table has, so the claim is bounded by
    data instead of a gap heuristic that stops short and leaves a second copy of
    the table drawn cell by cell on top of the rebuilt one.
    """
    cand = []
    for block in blocks:
        x0, y0, x1, y1 = block["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not (crop_bbox[0] - 4 <= cx <= crop_bbox[2] + 4
                and crop_bbox[1] - 4 <= cy <= crop_bbox[3] + 4):
            continue
        text = str(block.get("text", ""))
        if (block["size"] <= 8.2 and (y1 - y0) <= 34 and (x1 - x0) <= 420
                and len(text) <= 120):
            cand.append(block)
    if len(cand) < 4:
        return crop_bbox, []

    cand.sort(key=lambda b: b["bbox"][1])
    rows = []
    for block in cand:
        placed = False
        for row in rows:
            # same row when the vertical ranges overlap substantially; using
            # y0 alone splits a row whose cells are vertically centred
            # differently, which left the tail of the table unclaimed
            top = max(row["top"], block["bbox"][1])
            bottom = min(row["bottom"], block["bbox"][3])
            overlap = bottom - top
            shorter = min(row["bottom"] - row["top"], block["bbox"][3] - block["bbox"][1]) or 1
            if overlap > shorter * 0.5:
                row["items"].append(block)
                row["top"] = min(row["top"], block["bbox"][1])
                row["bottom"] = max(row["bottom"], block["bbox"][3])
                placed = True
                break
        if not placed:
            rows.append({"items": [block], "top": block["bbox"][1],
                         "bottom": block["bbox"][3]})
    rows.sort(key=lambda r: r["top"])

    take = rows[: row_count + 1]          # matrix rows + the header row
    claimed = [b for row in take for b in row["items"]]
    region = [min(b["bbox"][0] for b in claimed), min(b["bbox"][1] for b in claimed),
              max(b["bbox"][2] for b in claimed), max(b["bbox"][3] for b in claimed)]
    return region, [b["id"] for b in claimed]


MATH_RE = re.compile(r"[=∑√±×÷σσταβλμθΔ]|\^\s*2|_\s*\{")


def looks_like_formula(text):
    """Formula fragments are kept as original typesetting.

    Translating each fragment would drop Chinese into a box a few points tall
    and pile the fragments on top of one another.
    """
    text = str(text)
    return bool(MATH_RE.search(text)) and len(text) <= 45


def render(pdf_path, work, out_path, dpi=150, max_box_lines=4):
    set_dpi(dpi)
    src = pymupdf.open(pdf_path)
    zh, fig_map, fig_boxes, tables, matrices, skip_figs = load_all(work)
    max_fig, min_fig = fig_limits()

    out = pymupdf.open()
    stats = []

    for pno in range(1, src.page_count + 1):
        page = src[pno - 1]
        width_pt, height_pt = page.rect.width, page.rect.height
        pix = page.get_pixmap(dpi=DPI)
        base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        arr = np.asarray(base).copy()

        blocks = []
        bfile = work / "blocks" / f"p{pno:02d}.json"
        if bfile.exists():
            blocks = json.loads(bfile.read_text(encoding="utf-8"))
        translations = zh.get(pno, {})

        table_specs = []
        table_ids = set()
        for item in tables:
            if item["page"] != pno:
                continue
            matrix = matrices.get(item["file"])
            if not (matrix and matrix.get("header") and matrix.get("rows")):
                continue
            region, ids = cell_region(blocks, item["bbox"], len(matrix["rows"]))
            rows = [[str(c) for c in r] for r in matrix["rows"]]
            for row in rows:
                filled = [c.strip() for c in row if c.strip()]
                if len(row) > 1 and filled and len(set(filled)) == 1:
                    for i in range(1, len(row)):
                        row[i] = ""
            table_specs.append({"bbox": region, "erase": region,
                                "matrix": matrix, "rows": rows,
                                "cells": [b for b in blocks if b["id"] in ids]})
            table_ids.update(ids)

        occupied = []   # table bboxes are handled via table_ids, not here

        for spec in table_specs:
            # erase by the table's real ink extent, not by the crop rectangle
            extent, background = ink_extent(arr, [v * SCALE for v in spec["erase"]],
                                            pad=2, threshold=30)
            if extent is not None:
                spec["rect"] = extent
                arr[extent[1]:extent[3], extent[0]:extent[2]] = background
            else:
                spec["rect"] = [v * SCALE for v in spec["erase"]]

        figure_jobs, figure_rects = [], []
        fig_skipped = 0
        scratch_draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        for rect in _big_rects(page):
            suffix = f"_{int(rect.width)}x{int(rect.height)}.png"
            prefix = f"fig_p{pno:02d}_"
            key = next((k for k in fig_map
                        if k.startswith(prefix) and k.endswith(suffix)), None)
            if key is None or key in skip_figs:
                continue
            figure_rects.append([rect.x0, rect.y0, rect.x1, rect.y1])
            boxes = fig_boxes.get(key, [])
            mapping = fig_map.get(key, {}).get("boxes", {})
            factor = 150.0 / 200.0
            for index, box in enumerate(boxes, start=1):
                zh_text = mapping.get(str(index))
                if not zh_text or str(zh_text).strip().upper() == "SKIP":
                    continue
                bx0 = rect.x0 * SCALE + box[0] * factor * (DPI / 150.0)
                by0 = rect.y0 * SCALE + box[1] * factor * (DPI / 150.0)
                bx1 = rect.x0 * SCALE + box[2] * factor * (DPI / 150.0)
                by1 = rect.y0 * SCALE + box[3] * factor * (DPI / 150.0)
                lh = ink_line_height(arr, (bx0, by0, bx1, by1))
                # probe the fit first: erasing before knowing the text can be
                # drawn is what left blank rows behind
                base = lh * 1.05 if lh else (by1 - by0) * 0.55
                probe = draw_outlined(scratch_draw, (bx0, by0, bx1, by1), zh_text,
                                      max(min_fig, min(max_fig, base)), (0, 0, 0), min_fig)
                if probe is None:
                    fig_skipped += 1
                    continue
                if has_graphic_strokes(arr, (bx0, by0, bx1, by1)):
                    fig_skipped += 1
                    continue
                erase_glyphs(arr, (bx0, by0, bx1, by1))
                figure_jobs.append(((bx0, by0, bx1, by1), zh_text, lh))
        occupied.extend(figure_rects)

        def in_occupied(bbox):
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            for rect in occupied:
                if rect[0] - 4 <= cx <= rect[2] + 4 and rect[1] - 4 <= cy <= rect[3] + 4:
                    return True
            return False

        body_jobs, cell_jobs = [], []
        for block in blocks:
            text = translations.get(block["id"])
            if not text or should_skip(block["text"], str(text)):
                continue
            if block["id"] in table_ids or in_occupied(block["bbox"]):
                continue
            if looks_like_formula(block["text"]):
                continue     # keep the original math untouched
            box = [v * SCALE for v in block["bbox"]]
            draw_box, background = cover_ink(arr, box)
            if draw_box is None:
                continue
            if block["size"] <= 8.0 and (box[3] - box[1]) < 20:
                cell_jobs.append((draw_box, text, background))
            else:
                body_jobs.append((draw_box, text, block["size"] * SCALE, background))

        canvas = Image.fromarray(arr)
        draw = ImageDraw.Draw(canvas)

        # 1) figures
        fig_drawn = fig_skipped = 0
        for box, zh_text, line_h in figure_jobs:
            width, height = box[2] - box[0], box[3] - box[1]
            # match the original line height first; only fall back to a share of
            # the box when the ink could not be measured
            base = line_h * 1.05 if line_h else height * 0.55
            ref = max(min_fig, min(max_fig, base))
            if ref < min_fig:
                fig_skipped += 1
                continue
            if draw_outlined(draw, box, zh_text, ref, (0, 0, 0),
                             min_fig) is None:
                fig_skipped += 1
            else:
                fig_drawn += 1

        # 2) tables, confined to their reserved band
        extra_images = []
        for spec in table_specs:
            matrix = spec["matrix"]
            header = [str(c) for c in matrix["header"]]
            rows = spec["rows"]
            rect = spec.get("rect") or [v * SCALE for v in spec["bbox"]]
            x0 = rect[0]
            y0 = rect[1]
            table_width = max(120.0, rect[2] - rect[0])
            band_height = max(40.0, rect[3] - rect[1])
            widths = table_columns(spec.get("cells", []), len(header), table_width)
            if widths is None:
                widths = column_widths(header, rows, table_width)

            pages = None
            size = 13
            while size >= 7:
                pages = paginate(header, rows, widths, size, band_height - 4,
                                 canvas.height - 40)
                if len(pages) == 1:
                    break
                size -= 1
            if pages is None:
                continue
            chunk, cells, heights, hlines, hh = pages[0]
            draw_three_line(draw, x0, y0, widths, hlines, hh, cells, heights, size)
            for extra in pages[1:]:
                page_img = Image.new("RGB", (canvas.width, canvas.height), (255, 255, 255))
                page_draw = ImageDraw.Draw(page_img)
                c2, h2, hl2, hh2 = extra
                draw_three_line(page_draw, 20, 24, widths, hl2, hh2, c2, h2, size)
                extra_images.append(page_img)

        # 3) body text last
        for box, text, ref, background in body_jobs:
            lum = 255 if background is None else sum(background) / 3
            draw_text(draw, box, text, ref, BODY_INK if lum > 128 else (255, 255, 255))
        for box, text, background in cell_jobs:
            lum = 255 if background is None else sum(background) / 3
            draw_single_line(draw, box, text,
                             BODY_INK if lum > 128 else (255, 255, 255))

        header_translated = any(
            b["bbox"][1] < 46 and translations.get(b["id"]) for b in blocks)
        if pno >= 2 and not header_translated:
            band = pymupdf.Rect(0, 0, width_pt, 46)
            words = page.get_text("words", clip=band)
            left = [w for w in words if (w[0] + w[2]) / 2 < width_pt / 2]
            right = [w for w in words if (w[0] + w[2]) / 2 >= width_pt / 2]
            if left or right:
                tmp = np.asarray(canvas).copy()
                erase_glyphs(tmp, [0, 0, canvas.width, 44 * SCALE], threshold=55, grow=1)
                canvas.paste(Image.fromarray(tmp))
                draw = ImageDraw.Draw(canvas)
                for group, align_right in ((left, False), (right, True)):
                    if not group:
                        continue
                    text = translate_header(" ".join(w[4] for w in group))
                    font = font_of(int(5.5 * DPI / 72))
                    tw = draw.textlength(text, font=font)
                    tx = (canvas.width - 40 * DPI / 150 - tw) if align_right else 40 * DPI / 150
                    draw.text((tx, 18 * DPI / 150), text, font=font, fill=(70, 70, 70))

        out.insert_pdf(src, from_page=pno - 1, to_page=pno - 1)
        for index, image in enumerate([canvas] + extra_images):
            if index > 0:
                out.new_page(width=width_pt, height=height_pt)   # blank keeps parity
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", compress_level=1)
            buffer.seek(0)
            zh_page = out.new_page(width=width_pt, height=height_pt)
            zh_page.insert_image(zh_page.rect, stream=buffer.getvalue())

        stats.append({"page": pno, "tables": len(table_specs),
                      "extra": len(extra_images),
                      "fig_drawn": fig_drawn, "fig_skipped": fig_skipped})

    out.save(str(out_path), deflate=True, garbage=3)
    (work / "build_report_v5.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pages={out.page_count} dpi={DPI} -> {out_path}")
    for row in stats:
        if row["tables"] or row["fig_drawn"] or row["fig_skipped"]:
            print(f"  p{row['page']:02d} tables={row['tables']} "
                  f"fig+={row['fig_drawn']} fig-={row['fig_skipped']}")
    return 0


def _big_rects(page):
    found = []
    for info in page.get_images(full=True):
        try:
            for rect in page.get_image_rects(info[0]):
                if rect.width > 80 and rect.height > 60:
                    found.append(rect)
        except Exception:
            continue
    # one figure is often reported through several nested image rects; keep a
    # single copy or the same labels get painted twice, slightly offset
    rects = []
    for rect in sorted(found, key=lambda r: r.width * r.height, reverse=True):
        duplicate = False
        for kept in rects:
            ix = max(0.0, min(rect.x1, kept.x1) - max(rect.x0, kept.x0))
            iy = max(0.0, min(rect.y1, kept.y1) - max(rect.y0, kept.y0))
            if ix * iy > 0.6 * min(rect.width * rect.height, kept.width * kept.height):
                duplicate = True
                break
        if not duplicate:
            rects.append(rect)
    rects.sort(key=lambda r: (round(r.y0), round(r.x0)))
    return rects


if __name__ == "__main__":
    dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 150
    raise SystemExit(render(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]),
                            pathlib.Path(sys.argv[3]), dpi))


