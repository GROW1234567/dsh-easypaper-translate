"""Verify translation coverage and flag blocks that were left in English."""

import json
import pathlib
import re
import sys

CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    work = pathlib.Path(sys.argv[1])
    pages = sorted((work / "blocks").glob("p*.json"))
    total = translated = 0
    missing = []
    english_left = []
    short = []

    for block_file in pages:
        page = block_file.stem
        blocks = json.loads(block_file.read_text(encoding="utf-8"))
        zh_file = work / "zh" / f"{page}.json"
        zh = json.loads(zh_file.read_text(encoding="utf-8")) if zh_file.exists() else {}
        total += len(blocks)
        for block in blocks:
            key = block["id"]
            value = zh.get(key)
            if not value:
                missing.append(f"{page}:{key}")
                continue
            translated += 1
            value = str(value)
            if not CJK.search(value) and len(value) > 25:
                english_left.append(f"{page}:{key} :: {value[:60]}")
            if len(value) < 4 and len(block["text"]) > 40:
                short.append(f"{page}:{key} :: {value}")

    print(f"blocks_total={total}  translated={translated}  "
          f"coverage={translated / max(total,1):.1%}")
    if missing:
        print(f"\n缺失译文 ({len(missing)}):")
        for item in missing[:40]:
            print("  " + item)
    if english_left:
        print(f"\n疑似未翻译 ({len(english_left)}):")
        for item in english_left[:20]:
            print("  " + item)
    if short:
        print(f"\n译文过短 ({len(short)}):")
        for item in short[:20]:
            print("  " + item)

    fig_file = work / "figs" / "fig_zh.json"
    if fig_file.exists():
        figures = json.loads(fig_file.read_text(encoding="utf-8"))
        items = sum(len(v) for v in figures.values())
        print(f"\n图内文字: {len(figures)} 张图, {items} 条译文")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
