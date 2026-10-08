"""Build the URFD evaluation manifest and stream official PNG ZIPs to MP4."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "external"
URFD = DATA / "urfd"
RAW = URFD / "raw"
METADATA = URFD / "metadata"
VIDEOS = URFD / "videos"
MANIFEST = DATA / "dataset_manifest.csv"
SOURCE_BASE = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
LICENSE = "CC-BY-NC-SA-4.0"


def natural_key(name: str) -> tuple[object, ...]:
    import re

    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name))


def read_sync(clip_id: str) -> dict[int, int]:
    result: dict[int, int] = {}
    with (METADATA / f"{clip_id}-data.csv").open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            if len(row) >= 2:
                result[int(row[0])] = int(row[1])
    if not result:
        raise RuntimeError(f"No synchronization rows for {clip_id}")
    return result


def read_labels() -> dict[str, dict[int, int]]:
    labels: dict[str, dict[int, int]] = {}
    for name in ("urfall-cam0-falls.csv", "urfall-cam0-adls.csv"):
        with (METADATA / name).open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.reader(source):
                if len(row) >= 3:
                    labels.setdefault(row[0], {})[int(row[1])] = int(row[2])
    return labels


def timestamp(sync: dict[int, int], frame: int | None) -> str:
    if frame is None:
        return ""
    if frame in sync:
        return str(sync[frame])
    nearest = min(sync, key=lambda candidate: abs(candidate - frame))
    return str(sync[nearest])


def fps_for(sync: dict[int, int]) -> float:
    ordered = sorted(sync.items())
    deltas = [right[1] - left[1] for left, right in zip(ordered, ordered[1:]) if right[1] > left[1]]
    return round(1000.0 / statistics.median(deltas), 6)


def rows() -> list[dict[str, str]]:
    labels = read_labels()
    result: list[dict[str, str]] = []
    for kind, count in (("fall", 30), ("adl", 40)):
        for number in range(1, count + 1):
            clip_id = f"{kind}-{number:02d}"
            archive_name = f"{clip_id}-cam0-rgb.zip"
            archive = RAW / archive_name
            if not archive.is_file():
                raise FileNotFoundError(archive)
            sync = read_sync(clip_id)
            sequence_labels = labels.get(clip_id, {})
            falling = sorted(frame for frame, label in sequence_labels.items() if label == 0)
            lying = sorted(frame for frame, label in sequence_labels.items() if label == 1)
            fall_start = falling[0] if falling else None
            ground_contact = lying[0] if lying else None
            lying_end = lying[-1] if lying else None
            with zipfile.ZipFile(archive) as zip_file:
                frame_count = sum(1 for entry in zip_file.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".png"))
            split = "tune" if number <= 10 else "test"
            result.append(
                {
                    "clipId": clip_id,
                    "dataset": "URFD",
                    "sourceUrl": SOURCE_BASE + archive_name,
                    "license": LICENSE,
                    "split": split,
                    "eventType": "FALL" if kind == "fall" else "NONE",
                    "eventStartMs": timestamp(sync, fall_start),
                    "groundContactMs": timestamp(sync, ground_contact),
                    "eventEndMs": timestamp(sync, lying_end),
                    "expectedCount": "1" if kind == "fall" else "0",
                    "scenario": "official-fall" if kind == "fall" else "official-adl",
                    "people": "1",
                    "lighting": "dataset",
                    "fps": str(fps_for(sync)),
                    "frameCount": str(frame_count),
                    "archive": f"urfd/raw/{archive_name}",
                    "video": f"urfd/videos/{clip_id}.mp4",
                    "notes": "URFD official per-frame posture labels",
                }
            )
    return result


def write_manifest(items: list[dict[str, str]]) -> None:
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(items[0]))
        writer.writeheader()
        writer.writerows(items)


def convert(item: dict[str, str], ffmpeg: str) -> None:
    archive = DATA / item["archive"]
    output = DATA / item["video"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size > 0:
        print(f"exists: {output.name}", flush=True)
        return
    partial = output.with_suffix(".mp4.part")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-framerate",
        item["fps"],
        "-vcodec",
        "png",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "-y",
        str(partial),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        assert process.stdin is not None
        with zipfile.ZipFile(archive) as zip_file:
            frames = sorted(
                (entry for entry in zip_file.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".png")),
                key=lambda entry: natural_key(entry.filename),
            )
            for entry in frames:
                process.stdin.write(zip_file.read(entry))
        process.stdin.close()
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        partial.unlink(missing_ok=True)
        raise
    if return_code != 0 or not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg failed for {archive.name}: exit {return_code}")
    partial.replace(output)
    print(f"converted: {output.name} ({output.stat().st_size} bytes)", flush=True)


def write_video_checksums(items: list[dict[str, str]]) -> None:
    lines: list[str] = []
    for item in items:
        path = DATA / item["video"]
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        lines.append(f"{digest.hexdigest()}  videos/{path.name}")
    (URFD / "video-checksums.sha256").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--convert", action="store_true")
    parser.add_argument("--split", choices=("tune", "test", "all"), default="all")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    items = rows()
    write_manifest(items)
    if args.convert:
        import imageio_ffmpeg

        selected = [item for item in items if args.split == "all" or item["split"] == args.split]
        if args.limit:
            selected = selected[: args.limit]
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for index, item in enumerate(selected, 1):
            print(f"[{index}/{len(selected)}] {item['clipId']}", flush=True)
            convert(item, ffmpeg)
        write_video_checksums(items)
    summary = {
        "clips": len(items),
        "falls": sum(item["eventType"] == "FALL" for item in items),
        "adls": sum(item["eventType"] == "NONE" for item in items),
        "tune": sum(item["split"] == "tune" for item in items),
        "test": sum(item["split"] == "test" for item in items),
    }
    (URFD / "evaluation-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
