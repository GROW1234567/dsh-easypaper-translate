"""Crop detected table bands to PNG and record their page coordinates."""

import json
import pathlib
import sys

import pymupdf


def bands(blocks):
    cand = [b for b in blocks if b["size"] <= 8.2
            and (b["bbox"][3] - b["bbox"][1]) <= 40
            and (b["bbox"][2] - b["bbox"][0]) <= 400]
    cand.sort(key=lambda b: b["bbox"][1])
    out, cur = [], []
    for b in cand:
        if cur and b["bbox"][1] - max(x["bbox"][3] for x in cur) > 40:
            out.append(cur)
            cur = []
        cur.append(b)
    if cur:
        out.append(cur)
    result = []
    for group in out:
        if len(group) < 6:
            continue
        x0 = min(b["bbox"][0] for b in group)
        y0 = min(b["bbox"][1] for b in group)
        x1 = max(b["bbox"][2] for b in group)
        y1 = max(b["bbox"][3] for b in group)
        if y1 - y0 < 40:
            continue
        result.append((x0, y0, x1, y1))
    return result


def main() -> int:
    pdf = pathlib.Path(sys.argv[1])
    work = pathlib.Path(sys.argv[2])
    outdir = work / "tables"
    outdir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    records = []

    for pno, page in enumerate(doc, start=1):
        blocks = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            sizes = [s.get("size", 0) for line in block.get("lines", [])
                     for s in line.get("spans", [])]
            blocks.append({"bbox": block["bbox"], "size": max(sizes) if sizes else 0})
        for index, (x0, y0, x1, y1) in enumerate(bands(blocks), start=1):
            # pad: a little top, more bottom to catch the closing rule
            clip = pymupdf.Rect(max(0, x0 - 8), max(0, y0 - 8),
                                min(page.rect.width, x1 + 8),
                                min(page.rect.height - 20, y1 + 34))
            name = f"tbl_p{pno:02d}_{index}.png"
            pix = page.get_pixmap(clip=clip, dpi=200)
            pix.save(outdir / name)
            records.append({"page": pno, "file": name,
                            "bbox": [round(v, 1) for v in (clip.x0, clip.y0, clip.x1, clip.y1)]})

    (outdir / "tables.json").write_text(json.dumps(records, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"cropped {len(records)}")
    for r in records:
        print(f"  p{r['page']:02d} {r['file']} {r['bbox']}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
