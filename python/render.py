"""Render selected PDF pages to PNG for visual inspection."""

import pathlib
import sys

import pymupdf


def main() -> int:
    pdf = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    pages = [int(p) for p in sys.argv[3:]]
    outdir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    for pno in pages:
        if not (1 <= pno <= doc.page_count):
            continue
        page = doc[pno - 1]
        pix = page.get_pixmap(dpi=110)
        name = outdir / f"{pdf.stem[:20]}_p{pno:02d}.png"
        pix.save(name)
        print(f"{name}  {pix.width}x{pix.height}  {name.stat().st_size // 1024} KB")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
