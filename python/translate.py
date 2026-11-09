"""Single entry point for the local paper-translation pipeline.

Stages
  extract   PDF -> text blocks with coordinates            (no model calls)
  tables    PDF -> cropped table images + region list      (no model calls)
  figures   PDF -> cropped figure images + label boxes     (no model calls)
  build     render the bilingual PDF from the work folder  (no model calls)
  run       all of the above in order

The model only fills work/zh*/pNN.json and work/tables/matrices.json; every
stage here is local, so re-running costs nothing.

Examples
  python translate.py run paper.pdf --dpi 300
  python translate.py build paper.pdf --dpi 200
  python translate.py extract paper.pdf
"""

import pathlib as _p, sys as _s
_here = _p.Path(__file__).resolve().parent
for _cand in (_here / ".pylibs", _here.parent / ".pylibs", _here):
    if _cand.exists() and str(_cand) not in _s.path:
        _s.path.insert(0, str(_cand))
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DPI_CHOICES = (150, 200, 300, 600, 1200)
DEFAULT_DPI = 200


def stage_extract(pdf: pathlib.Path, work: pathlib.Path) -> None:
    import extract_blocks
    sys.argv = ["extract_blocks", str(pdf), str(work)]
    extract_blocks.main()


def stage_tables(pdf: pathlib.Path, work: pathlib.Path) -> None:
    import crop_tables
    sys.argv = ["crop_tables", str(pdf), str(work)]
    crop_tables.main()


def stage_figures(pdf: pathlib.Path, work: pathlib.Path, dpi: int,
                  image_dpi: int = 200) -> None:
    import crop_figs
    import fig_boxes
    figs = work / "figs"
    sys.argv = ["crop_figs", str(pdf), str(figs), str(image_dpi)]
    crop_figs.main()
    sys.argv = ["fig_boxes", str(figs), str(figs / "overlay")]
    fig_boxes.main()


NAME_FIELDS_HELP = ("Fields: {zh_title} {en_title} {dpi} {pages} {date} {stem}. "
                     "Default: [中英对照]{zh_title}+{en_title}")


def output_name(pdf: pathlib.Path, work: pathlib.Path, template: str = "",
                dpi: int = 0) -> str:
    """Render the output file name from the configured template."""
    zh = ""
    blocks_file = work / "blocks" / "p01.json"
    zh_file = work / "zh" / "p01.json"
    if blocks_file.exists() and zh_file.exists():
        try:
            import engine as _engine
            blocks = json.loads(blocks_file.read_text(encoding="utf-8"))
            table = _engine._as_map(json.loads(zh_file.read_text(encoding="utf-8")))
            body = [b for b in blocks
                    if b.get("id", "").startswith("b")
                    and b["bbox"][1] > 60
                    and len(b.get("text", "")) > 15]
            if body:
                biggest = max(b.get("size", 0) for b in body)
                # the journal banner can out-size the title; the title is the
                # long line among the near-largest blocks
                near = [b for b in body if b.get("size", 0) >= biggest * 0.85]
                title = max(near, key=lambda b: len(b.get("text", "")), default=None)
            else:
                title = None
            if title:
                zh = str(table.get(title["id"], "")).strip()
        except Exception:
            zh = ""
    zh = zh.replace("/", "_").replace("\\", "_")[:60]
    stem = pdf.stem
    template = template or "[中英对照]{zh_title}+{en_title}"
    try:
        pages = len(list((work / "blocks").glob("p*.json")))
    except Exception:
        pages = 0
    import datetime
    fields = {
        "zh_title": zh,
        "en_title": stem,
        "stem": stem,
        "dpi": str(dpi),
        "pages": str(pages),
        "date": datetime.date.today().isoformat(),
    }
    try:
        name = template.format(**fields)
    except (KeyError, IndexError):
        name = f"[中英对照]{zh or stem}"
    name = name.replace("/", "_").replace("\\", "_").strip()
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def stage_build(pdf: pathlib.Path, work: pathlib.Path, dpi: int,
                max_box_lines: int = 4, template: str = "") -> pathlib.Path:
    import engine
    out = pdf.with_name(output_name(pdf, work, template, dpi))
    engine.render(pdf, work, out, dpi, max_box_lines)
    return out


def missing_translations(work: pathlib.Path) -> list[str]:
    """Which pages still need model work."""
    pages = sorted((work / "blocks").glob("p*.json"))
    have = set()
    for folder in ("zh", "zh2", "zh3"):
        for path in (work / folder).glob("p*.json"):
            have.add(path.stem)
    return [p.stem for p in pages if p.stem not in have]


def stage_selftest() -> int:
    """Report whether the bundled dependencies import."""
    try:
        import pymupdf
        import scipy
        import yaml
    except Exception as error:  # noqa: BLE001 - reported to the caller
        print(f"deps missing: {error}")
        return 1
    print(f"deps ok: pymupdf {pymupdf.__version__}, scipy {scipy.__version__}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["extract", "tables", "figures", "build", "run", "selftest"])
    parser.add_argument("pdf", type=pathlib.Path, nargs="?")
    parser.add_argument("--dpi", type=int, choices=DPI_CHOICES, default=DEFAULT_DPI,
                        help="output resolution: " + ", ".join(map(str, DPI_CHOICES)))
    parser.add_argument("--work", type=pathlib.Path, default=pathlib.Path("work"))
    parser.add_argument("--img-dpi", type=int, default=200,
                        help="resolution used when cropping figures/tables (default 200)")
    parser.add_argument("--name-template", default="",
                        help=NAME_FIELDS_HELP)
    parser.add_argument("--max-box-lines", type=int, default=4,
                        help="skip figure boxes holding more text lines than this "
                             "(0 = no limit; without a limit a multi-row box is "
                             "erased but only one string drawn back)")
    args = parser.parse_args()

    if args.stage == "selftest":
        return stage_selftest()

    pdf = args.pdf.expanduser().resolve()
    if not pdf.exists():
        parser.error(f"PDF not found: {pdf}")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)

    if args.stage in ("extract", "run"):
        stage_extract(pdf, work)
    if args.stage in ("tables", "run"):
        stage_tables(pdf, work)
    if args.stage in ("figures", "run"):
        stage_figures(pdf, work, args.dpi, args.img_dpi)

    if args.stage in ("build", "run"):
        pending = missing_translations(work)
        if pending:
            print(f"\n{len(pending)} page(s) still need translation: "
                  f"{', '.join(pending[:12])}{' ...' if len(pending) > 12 else ''}")
            print("Fill work/zh*/pNN.json, then re-run: build")
            if args.stage == "run":
                return 1
        out = stage_build(pdf, work, args.dpi, args.max_box_lines,
                          args.name_template)
        print(f"\noutput: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
