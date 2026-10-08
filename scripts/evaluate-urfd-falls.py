"""Evaluate the production fall state machine on the fixed URFD split."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import cv2
import torch
from ultralytics import YOLO
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algorithm.fall_detector import (  # noqa: E402
    FallConfig,
    TemporalFallDetector,
    compute_pose_features,
)
from algorithm.pose_utils import select_largest_pose  # noqa: E402


MANIFEST = ROOT / "data" / "external" / "dataset_manifest.csv"
OUTPUT = ROOT / "output" / "evaluation" / "urfd"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> tuple[dict[str, object], FallConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Fall configuration must be a YAML mapping")
    allowed = {"model", "preprocessing", "fall_detector"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown top-level configuration keys: {sorted(unknown)}")
    model = raw.get("model", {})
    detector = raw.get("fall_detector", {})
    if not isinstance(model, dict) or not isinstance(detector, dict):
        raise ValueError("model and fall_detector must be mappings")
    return model, FallConfig.from_mapping(detector)


def load_manifest(split: str, limit: int, clips: set[str]) -> list[dict[str, str]]:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as source:
        rows = [
            row
            for row in csv.DictReader(source)
            if (split == "all" or row["split"] == split)
            and (not clips or row["clipId"] in clips)
        ]
    if limit:
        rows = rows[:limit]
    if not rows:
        raise RuntimeError(f"No manifest entries for split {split}")
    return rows


def evaluate_clip(
    item: dict[str, str],
    model: YOLO,
    model_confidence: float,
    detector_config: FallConfig,
    device: str,
) -> dict[str, object]:
    video = ROOT / "data" / "external" / item["video"]
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = float(item["fps"])
    detector = TemporalFallDetector(detector_config)
    predictions: list[int] = []
    pose_frames = 0
    frame_count = 0
    max_velocity = 0.0
    max_aspect = 0.0
    max_torso = 0.0
    state_transitions: list[dict[str, object]] = []
    previous_state = detector.state
    started = time.perf_counter()
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp_seconds = frame_count / fps
            result = model.predict(
                frame,
                conf=model_confidence,
                device=device,
                verbose=False,
            )[0]
            pose = select_largest_pose(result)
            features = None
            if pose is not None:
                features = compute_pose_features(
                    keypoints_xy=pose.keypoints_xy,
                    keypoints_confidence=pose.keypoints_confidence,
                    bbox_xyxy=pose.bbox_xyxy,
                    frame_height=frame.shape[0],
                    min_confidence=detector_config.min_keypoint_confidence,
                )
            if features is not None:
                pose_frames += 1
                max_aspect = max(max_aspect, features.bbox_aspect_ratio)
                max_torso = max(max_torso, features.torso_angle_deg)
            decision = detector.update(features, timestamp_seconds)
            max_velocity = max(max_velocity, decision.downward_velocity)
            if decision.state != previous_state:
                state_transitions.append(
                    {
                        "timeMs": round(timestamp_seconds * 1000),
                        "from": previous_state.value,
                        "to": decision.state.value,
                        "velocity": decision.downward_velocity,
                        "isLying": decision.is_lying,
                        "aspectRatio": features.bbox_aspect_ratio if features else None,
                        "torsoAngle": features.torso_angle_deg if features else None,
                        "hipY": features.hip_y_normalized if features else None,
                        "bboxBottom": features.bbox_bottom_normalized if features else None,
                        "reason": decision.reason,
                    }
                )
                previous_state = decision.state
            if decision.event_started:
                predictions.append(round(timestamp_seconds * 1000))
            frame_count += 1
    finally:
        capture.release()
    elapsed = time.perf_counter() - started
    expected = item["eventType"] == "FALL"
    detected = bool(predictions)
    ground_contact = int(item["groundContactMs"]) if item["groundContactMs"] else None
    latency = predictions[0] - ground_contact if predictions and ground_contact is not None else None
    return {
        "clipId": item["clipId"],
        "split": item["split"],
        "expectedFall": expected,
        "detectedFall": detected,
        "outcome": "TP" if expected and detected else "FN" if expected else "FP" if detected else "TN",
        "predictionTimesMs": predictions,
        "duplicateEvents": max(0, len(predictions) - 1),
        "eventStartMs": int(item["eventStartMs"]) if item["eventStartMs"] else None,
        "groundContactMs": ground_contact,
        "eventEndMs": int(item["eventEndMs"]) if item["eventEndMs"] else None,
        "latencyFromGroundMs": latency,
        "frames": frame_count,
        "durationSeconds": frame_count / fps,
        "poseCoverage": pose_frames / frame_count if frame_count else 0.0,
        "maxDownwardVelocity": max_velocity,
        "maxAspectRatio": max_aspect,
        "maxTorsoAngle": max_torso,
        "stateTransitions": state_transitions,
        "processingSeconds": elapsed,
        "processingFps": frame_count / elapsed if elapsed else 0.0,
    }


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def summarize(results: list[dict[str, object]]) -> dict[str, object]:
    counts = {key: sum(result["outcome"] == key for result in results) for key in ("TP", "FP", "TN", "FN")}
    negative_hours = sum(float(result["durationSeconds"]) for result in results if not result["expectedFall"]) / 3600
    latencies = [int(result["latencyFromGroundMs"]) for result in results if result["latencyFromGroundMs"] is not None]
    precision = ratio(counts["TP"], counts["TP"] + counts["FP"])
    recall = ratio(counts["TP"], counts["TP"] + counts["FN"])
    false_alerts_per_hour = counts["FP"] / negative_hours if negative_hours else 0.0
    return {
        **counts,
        "precision": precision,
        "recall": recall,
        "falseAlertsPerHour": false_alerts_per_hour,
        "meanPoseCoverage": statistics.mean(float(result["poseCoverage"]) for result in results),
        "meanProcessingFps": statistics.mean(float(result["processingFps"]) for result in results),
        "medianLatencyFromGroundMs": statistics.median(latencies) if latencies else None,
        "duplicateEvents": sum(int(result["duplicateEvents"]) for result in results),
        "gates": {
            "precisionAtLeast0.80": precision >= 0.80,
            "recallAtLeast0.90": recall >= 0.90,
            "falseAlertsPerHourAtMost1": false_alerts_per_hour <= 1.0,
            "noDuplicateEvents": all(int(result["duplicateEvents"]) == 0 for result in results),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("tune", "test", "all"), default="tune")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "fall_detection.yaml")
    parser.add_argument("--name", default="baseline")
    parser.add_argument("--clip", action="append", default=[])
    args = parser.parse_args()
    config_path = args.config.resolve()
    model_config, detector_config = load_config(config_path)
    model_path = (ROOT / str(model_config.get("path", "yolov8n-pose.pt"))).resolve()
    confidence = float(model_config.get("confidence", 0.55))
    model = YOLO(str(model_path))
    items = load_manifest(args.split, args.limit, set(args.clip))
    results: list[dict[str, object]] = []
    for index, item in enumerate(items, 1):
        print(f"[{index}/{len(items)}] {item['clipId']}", flush=True)
        result = evaluate_clip(item, model, confidence, detector_config, args.device)
        results.append(result)
        print(
            f"  {result['outcome']} events={len(result['predictionTimesMs'])} "
            f"pose={result['poseCoverage']:.1%} fps={result['processingFps']:.1f}",
            flush=True,
        )
    summary = summarize(results)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(character for character in args.name if character.isalnum() or character in "-_")
    if not safe_name:
        raise ValueError("Evaluation name must contain letters, digits, '-' or '_'")
    stem = f"{args.split}-{safe_name}" + (f"-limit-{args.limit}" if args.limit else "")
    report = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "split": args.split,
        "device": args.device,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch": torch.__version__,
        "model": str(model_path),
        "modelSha256": file_hash(model_path),
        "config": str(config_path),
        "configSha256": file_hash(config_path),
        "summary": summary,
        "clips": results,
    }
    (OUTPUT / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUTPUT / f"{stem}.csv").open("w", encoding="utf-8-sig", newline="") as output:
        json_fields = {"predictionTimesMs", "stateTransitions"}
        fields = [key for key in results[0] if key not in json_fields] + sorted(json_fields)
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                result
                | {
                    "predictionTimesMs": json.dumps(result["predictionTimesMs"]),
                    "stateTransitions": json.dumps(result["stateTransitions"], ensure_ascii=False),
                }
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
