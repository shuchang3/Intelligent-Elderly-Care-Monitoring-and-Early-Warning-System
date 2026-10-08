"""Download the approved URFD/UP-Fall evaluation subset from official links.

Raw archives are intentionally ignored by Git. The script is restart-safe:
completed files are retained, partial downloads use a .part suffix, and every
completed run refreshes the SHA-256 list.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from html import unescape
import re
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "external"
URFD_BASE = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
UPFALL_PAGE = DATA_ROOT / "upfall" / "docs" / "official-dataset-page.html"
MANIFEST = DATA_ROOT / "download-manifest.csv"
ERRORS = DATA_ROOT / "download-errors.csv"
UPFALL_SUBJECTS = {1, 2}
UPFALL_ACTIVITIES = {8, 9, 11}


def planned_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for kind, count in (("fall", 30), ("adl", 40)):
        for number in range(1, count + 1):
            name = f"{kind}-{number:02d}-cam0-rgb.zip"
            rows.append(
                {
                    "dataset": "URFD",
                    "clipId": name.removesuffix(".zip"),
                    "activityId": "FALL" if kind == "fall" else "ADL",
                    "subject": "",
                    "trial": "",
                    "camera": "0",
                    "url": URFD_BASE + name,
                    "relativePath": f"urfd/raw/{name}",
                }
            )

    source = unescape(UPFALL_PAGE.read_text(encoding="utf-8", errors="replace"))
    blocks = re.finditer(
        r'<div id="Subject(\d+)Activity(\d+)Trial(\d+)"[^>]*>(.*?)(?=<div id="Subject|\Z)',
        source,
        re.DOTALL,
    )
    for block in blocks:
        subject, activity, trial = map(int, block.group(1, 2, 3))
        if subject not in UPFALL_SUBJECTS or activity not in UPFALL_ACTIVITIES:
            continue
        camera = re.search(
            r'<a href="([^"]+)">Camera1</a>', block.group(4), re.DOTALL
        )
        if not camera:
            raise RuntimeError(
                f"Official Camera1 link missing for S{subject} A{activity} T{trial}"
            )
        url = camera.group(1).replace("/a/up.edu.mx/uc?", "/uc?")
        name = f"subject-{subject:02d}-activity-{activity:02d}-trial-{trial}-camera-1.zip"
        rows.append(
            {
                "dataset": "UP-Fall",
                "clipId": name.removesuffix(".zip"),
                "activityId": str(activity),
                "subject": str(subject),
                "trial": str(trial),
                "camera": "1",
                "url": url,
                "relativePath": f"upfall/raw/{name}",
            }
        )
    if sum(row["dataset"] == "UP-Fall" for row in rows) != 18:
        raise RuntimeError("Expected 18 UP-Fall Camera1 files from the official page")
    return rows


def write_manifest(rows: list[dict[str, str]], errors: dict[str, str] | None = None) -> None:
    errors = errors or {}
    fields = list(rows[0]) + ["status", "sizeBytes", "sha256"]
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            path = DATA_ROOT / row["relativePath"]
            writer.writerow(
                row
                | {
                    "status": (
                        "DOWNLOADED"
                        if path.is_file()
                        else "BLOCKED"
                        if row["relativePath"] in errors
                        else "PENDING"
                    ),
                    "sizeBytes": str(path.stat().st_size) if path.is_file() else "",
                    "sha256": sha256(path) if path.is_file() else "",
                }
            )


def read_errors() -> dict[str, str]:
    if not ERRORS.is_file():
        return {}
    with ERRORS.open("r", encoding="utf-8-sig", newline="") as source:
        return {
            row["relativePath"]: row["error"]
            for row in csv.DictReader(source)
            if row.get("relativePath")
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_http(url: str, output: Path) -> None:
    partial = output.with_suffix(output.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "SJWJ-academic-dataset/1.0"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=60) as response:
        append = existing > 0 and response.status == 206
        mode = "ab" if append else "wb"
        with partial.open(mode) as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
    partial.replace(output)


def download_upfall(url: str, output: Path) -> None:
    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError(
            "UP-Fall requires gdown; install requirements-datasets.txt first"
        ) from exc
    partial = output.with_suffix(output.suffix + ".part")
    result = gdown.download(url=url, output=str(partial), quiet=False, fuzzy=True)
    if not result or not partial.is_file():
        raise RuntimeError(f"Google Drive download failed: {url}")
    partial.replace(output)


def write_checksums(rows: list[dict[str, str]]) -> None:
    for dataset in ("urfd", "upfall"):
        directory = DATA_ROOT / dataset / "raw"
        files = sorted(path for path in directory.glob("*.zip") if path.is_file())
        lines = [f"{sha256(path)}  raw/{path.name}" for path in files]
        (DATA_ROOT / dataset / "checksums.sha256").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=("urfd", "upfall", "all"), default="all")
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    rows = planned_rows()
    previous_errors = read_errors()
    write_manifest(rows, previous_errors)
    if args.manifest_only:
        return
    errors: dict[str, str] = {}
    for index, row in enumerate(rows, 1):
        if args.dataset != "all" and row["dataset"].lower().replace("-", "") != args.dataset.replace("-", ""):
            continue
        output = DATA_ROOT / row["relativePath"]
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.is_file():
            print(f"[{index}/{len(rows)}] exists: {output.name}", flush=True)
            continue
        print(f"[{index}/{len(rows)}] download: {output.name}", flush=True)
        try:
            if row["dataset"] == "URFD":
                download_http(row["url"], output)
            else:
                download_upfall(row["url"], output)
            print(f"  completed: {output.stat().st_size} bytes", flush=True)
        except Exception as exc:  # continue so one provider quota does not hide other files
            errors[row["relativePath"]] = f"{type(exc).__name__}: {str(exc)[:500]}"
            print(f"  blocked: {errors[row['relativePath']]}", flush=True)
    write_checksums(rows)
    if errors:
        with ERRORS.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("relativePath", "error"))
            writer.writerows(sorted(errors.items()))
    elif ERRORS.exists():
        ERRORS.unlink()
    write_manifest(rows, errors)


if __name__ == "__main__":
    main()
