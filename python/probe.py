"""Probe two PDFs: structure, text layer, layout, images.

Zero-cost local analysis: no model calls, no network. Prints a compact
report so the agent can decide which pipeline is feasible.
"""

import pathlib
import statistics
import sys

import pymupdf


def column_profile(page) -> str:
    """Guess single vs multi-column from text-block x positions."""
    blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and b[4].strip()]
    if len(blocks) < 6:
        return "n/a"
    widths = []
    for b in blocks:
        x0, _, x1, _, _ = b[:5]
        widths.append((x0, x1))
    mid = page.rect.width / 2
    left = sum(1 for x0, x1 in widths if x1 < mid + 5)
    right = sum(1 for x0, x1 in widths if x0 > mid - 5)
    span = sum(1 for x0, x1 in widths if x0 < mid - 5 and x1 > mid + 5)
    if left >= 3 and right >= 3 and span <= 1:
        return f"双栏(left={left}, right={right})"
    return f"单栏(left={left}, right={right}, span={span})"


def inspect(path: pathlib.Path, label: str) -> None:
    doc = pymupdf.open(path)
    pages = doc.page_count
    chars = []
    no_text = 0
    img_total = 0
    img_pages = 0
    vec_text_pages = 0
    draw_total = 0

    for page in doc:
        text = page.get_text("text")
        n = len(text.strip())
        chars.append(n)
        if n < 20:
            no_text += 1
        imgs = page.get_images(full=True)
        if imgs:
            img_pages += 1
            img_total += len(imgs)
        draw_total += len(page.get_drawings())
        if n >= 200:
            vec_text_pages += 1

    total = sum(chars)
    print(f"\n=== {label} ===")
    print(f"文件      : {path.name}")
    print(f"大小      : {path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"页数      : {pages}")
    print(f"文字总量  : {total:,} 字符  (平均 {total // max(pages,1):,}/页)")
    print(f"无文字页  : {no_text} / {pages}")
    print(f"嵌图总数  : {img_total}  出现在 {img_pages} 页")
    print(f"矢量绘制  : {draw_total} 个绘图对象")
    print(f"类型判断  : {'电子版(有文字层)' if total / max(pages,1) > 200 else '疑似扫描件/图片版'}")

    if total:
        print(f"字符中位数: {statistics.median(chars):,.0f}   最小 {min(chars):,}   最大 {max(chars):,}")

    # per-page image density (figures usually cluster on a few pages)
    dense = []
    for index, page in enumerate(doc, start=1):
        imgs = page.get_images(full=True)
        big = 0
        for info in imgs:
            xref = info[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for r in rects:
                if r.width > 80 and r.height > 60:
                    big += 1
        if big:
            dense.append((index, big))

    print(f"含大图页  : {len(dense)} 页 -> {dense[:15]}{' ...' if len(dense) > 15 else ''}")

    sample = [p for p in (1, 2, 3, 4) if p <= pages]
    print("版面采样  :")
    for pno in sample:
        page = doc[pno - 1]
        blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and b[4].strip()]
        print(f"  第{pno}页  文字块={len(blocks):3d}  {column_profile(page)}")

    # vector text inside figure areas is what we hope for
    print("字号分布  :", end=" ")
    sizes = {}
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    key = round(span["size"], 1)
                    sizes[key] = sizes.get(key, 0) + len(span["text"].strip())
    top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    print(", ".join(f"{s}pt:{n}" for s, n in top))

    doc.close()


def main() -> int:
    paths = [pathlib.Path(p) for p in sys.argv[1:]]
    for index, path in enumerate(paths, start=1):
        if not path.exists():
            print(f"missing: {path}")
            continue
        label = "原文" if index == 1 else "译本"
        inspect(path, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
