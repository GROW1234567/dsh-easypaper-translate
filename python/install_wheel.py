"""Minimal wheel installer that avoids pip's temp-directory machinery.

Usage: python install_wheel.py <package-name> [--libs DIR] [--tmp DIR]

Downloads the best-matching win_amd64 wheel from PyPI and extracts it into
the libs directory as a plain directory tree (a .whl is just a zip).
Kept inside the session workspace so no elevated file access is needed.
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
import urllib.request
import zipfile


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def pick_wheel(files: list[dict]) -> dict:
    wheels = [f for f in files if f["filename"].endswith(".whl")]
    if not wheels:
        raise SystemExit("no wheels published for this package")

    def score(item: dict) -> tuple:
        name = item["filename"].lower()
        return (
            "win_amd64" in name,
            "abi3" in name,
            "cp312" in name,
            "none-any" in name,
        )

    wheels.sort(key=score, reverse=True)
    best = wheels[0]
    if "win_amd64" not in best["filename"].lower() and "none-any" not in best["filename"].lower():
        print(f"warning: no windows wheel found, using {best['filename']}", file=sys.stderr)
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("--libs", default=".pylibs")
    parser.add_argument("--tmp", default=".tmp")
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    libs = root / args.libs
    tmp = root / args.tmp
    libs.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)

    meta = fetch_json(f"https://pypi.org/pypi/{args.package}/json")
    wheel = pick_wheel(meta["urls"])
    print(f"package={meta['info']['name']} version={meta['info']['version']}")
    print(f"wheel={wheel['filename']} size={wheel['size']}")

    archive = tmp / wheel["filename"]
    urllib.request.urlretrieve(wheel["url"], archive)
    print(f"downloaded={archive.stat().st_size}")

    with zipfile.ZipFile(archive) as handle:
        handle.extractall(libs)
    print(f"extracted_to={libs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
