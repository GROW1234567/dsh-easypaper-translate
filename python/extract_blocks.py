"""Extract translatable text blocks from a PDF, page by page.

Produces:
  work/blocks/pNN.json   structured blocks (id, bbox, size, text)
  work/text/pNN.txt      "bNN<TAB>text" lines for translation
  work/manifest.json     page-level summary

Skips: whitespace-only, single characters, and text below MIN_PT.
"""

import json
import pathlib
import re
import sys

import pymupdf

MIN_PT = 4.5          # below this a glyph is unreadable at 150 dpi
MIN_CHARS = 2
SKIP_TOP = 0.045      # header band (fraction of page height)
SKIP_BOTTOM = 0.035   # footer band


def clean(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def main() -> int:
    src = pathlib.Path(sys.argv[1])
    root = pathlib.Path(sys.argv[2])
    (root / "blocks").mkdir(parents=True, exist_ok=True)
    (root / "text").mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(src)
    manifest = []

    for pno, page in enumerate(doc, start=1):
        height = page.rect.height
        raw = page.get_text("dict")
        blocks = []
        index = 0
        for block in raw["blocks"]:
            if block.get("type") != 0:
                continue
            lines = []
            sizes = []
            colours = []
            for line in block.get("lines", []):
                piece = ""
                for span in line.get("spans", []):
                    piece += span.get("text", "")
                    sizes.append(round(span.get("size", 0), 1))
                    colours.append(span.get("color", 0))
                if piece.strip():
                    lines.append(piece)
            text = clean(" ".join(lines))
            if len(text) < MIN_CHARS:
                continue
            bbox = block["bbox"]
            y0 = bbox[1]
            if y0 < height * SKIP_TOP or bbox[3] > height * (1 - SKIP_BOTTOM):
                continue
            size = max(sizes) if sizes else 0
            if size < MIN_PT:
                continue
            index += 1
            blocks.append({
                "id": f"b{index:02d}",
                "bbox": [round(v, 1) for v in bbox],
                "size": size,
                "colour": max(set(colours), key=colours.count) if colours else 0,
                "text": text,
            })

        # running head: kept out of the normal block list so existing ids stay
        # stable, but exposed as h01.. so it can be translated like any block
        header_blocks = []
        words = page.get_text("words", clip=pymupdf.Rect(0, 0, page.rect.width, 46))
        halves = ([w for w in words if (w[0] + w[2]) / 2 < page.rect.width / 2],
                  [w for w in words if (w[0] + w[2]) / 2 >= page.rect.width / 2])
        for head_index, group in enumerate(halves, start=1):
            if not group:
                continue
            htext = clean(" ".join(w[4] for w in group))
            if len(htext) < 3:
                continue
            header_blocks.append({
                "id": f"h{head_index:02d}",
                "bbox": [round(min(w[0] for w in group), 1),
                         round(min(w[1] for w in group), 1),
                         round(max(w[2] for w in group), 1),
                         round(max(w[3] for w in group), 1)],
                "size": 6.5,
                "colour": 0,
                "text": htext,
            })
        if header_blocks:
            blocks = header_blocks + blocks

        (root / "blocks" / f"p{pno:02d}.json").write_text(
            json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
        with (root / "text" / f"p{pno:02d}.txt").open("w", encoding="utf-8") as handle:
            for block in blocks:
                handle.write(f"{block['id']}\t{block['text']}\n")

        chars = sum(len(b["text"]) for b in blocks)
        manifest.append({
            "page": pno,
            "blocks": len(blocks),
            "chars": chars,
            "min_size": min((b["size"] for b in blocks), default=0),
            "max_size": max((b["size"] for b in blocks), default=0),
        })

    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"pages={len(manifest)}")
    print("page blocks chars  min_pt max_pt")
    for row in manifest:
        print(f"{row['page']:4d} {row['blocks']:6d} {row['chars']:6d} "
              f"{row['min_size']:6.1f} {row['max_size']:6.1f}")
    print(f"total chars={sum(r['chars'] for r in manifest)}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
