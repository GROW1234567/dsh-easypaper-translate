"""Crop embedded figure regions to PNG at a chosen DPI for vision OCR trials."""

import pathlib
import sys

import pymupdf


def main() -> int:
    pdf = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    dpi = int(sys.argv[3])
    pages = [int(p) for p in sys.argv[4:]]
    outdir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)

    if not pages:
        # no explicit list: take every page that actually carries a big figure
        pages = []
        for pno in range(1, doc.page_count + 1):
            page = doc[pno - 1]
            for info in page.get_images(full=True):
                try:
                    rects = page.get_image_rects(info[0])
                except Exception:
                    continue
                if any(r.width > 80 and r.height > 60 for r in rects):
                    pages.append(pno)
                    break
        print(f"auto-detected {len(pages)} figure page(s)")

    for pno in pages:
        page = doc[pno - 1]
        kept = []                      # rects already written for this page
        for info in page.get_images(full=True):
            xref = info[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            for index, rect in enumerate(rects, start=1):
                if rect.width < 80 or rect.height < 60:
                    continue
                # the same figure is often reported twice (nested image rects);
                # one crop is enough, a second would be translated twice
                duplicate = False
                for other in kept:
                    ix = max(0.0, min(rect.x1, other.x1) - max(rect.x0, other.x0))
                    iy = max(0.0, min(rect.y1, other.y1) - max(rect.y0, other.y0))
                    inter = ix * iy
                    if inter > 0.6 * min(rect.width * rect.height,
                                          other.width * other.height):
                        duplicate = True
                        break
                if duplicate:
                    continue
                kept.append(rect)
                scale = dpi / 72
                pix = page.get_pixmap(
                    clip=rect,
                    matrix=pymupdf.Matrix(scale, scale),
                )
                name = outdir / f"fig_p{pno:02d}_{index}_{int(rect.width)}x{int(rect.height)}.png"
                pix.save(name)
                print(f"{name}  {pix.width}x{pix.height}  {name.stat().st_size // 1024} KB")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
