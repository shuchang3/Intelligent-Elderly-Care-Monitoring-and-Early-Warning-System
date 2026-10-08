"""Helpers for converting Ultralytics pose results into project data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


COCO_KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

NormalizedRoi = tuple[float, float, float, float]


def box_iou(first: np.ndarray, second: np.ndarray) -> float:
    """Return intersection-over-union for two ``xyxy`` boxes."""

    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, float(first[2] - first[0])) * max(
        0.0, float(first[3] - first[1])
    )
    second_area = max(0.0, float(second[2] - second[0])) * max(
        0.0, float(second[3] - second[1])
    )
    union = first_area + second_area - intersection
    return 0.0 if union <= 0 else intersection / union


def match_boxes_one_to_one(
    tracked_boxes: list[np.ndarray], pose_boxes: np.ndarray, minimum_iou: float = 0.3
) -> dict[int, int]:
    """Greedily assign the strongest unique track/pose overlaps.

    Sorting all candidate pairs before assigning prevents an early track from
    consuming a pose that overlaps another track much more strongly.
    """

    candidates = sorted(
        (
            (box_iou(track_box, pose_box), track_index, pose_index)
            for track_index, track_box in enumerate(tracked_boxes)
            for pose_index, pose_box in enumerate(pose_boxes)
        ),
        reverse=True,
    )
    assignments: dict[int, int] = {}
    used_poses: set[int] = set()
    for overlap, track_index, pose_index in candidates:
        if overlap < minimum_iou:
            break
        if track_index in assignments or pose_index in used_poses:
            continue
        assignments[track_index] = pose_index
        used_poses.add(pose_index)
    return assignments


@dataclass(frozen=True)
class SelectedPose:
    """One person's box and 17 COCO keypoints from a video frame."""

    person_index: int
    bbox_xyxy: np.ndarray
    bbox_confidence: float
    keypoints_xy: np.ndarray
    keypoints_confidence: np.ndarray


def parse_normalized_roi(value: object) -> NormalizedRoi | None:
    """Validate an optional normalized ``(x1, y1, x2, y2)`` crop."""

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("preprocessing.roi must contain four normalized numbers")
    x1, y1, x2, y2 = (float(item) for item in value)
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError(
            "preprocessing.roi must satisfy 0 <= x1 < x2 <= 1 and "
            "0 <= y1 < y2 <= 1"
        )
    return x1, y1, x2, y2


def crop_frame_to_roi(
    frame: np.ndarray, roi: NormalizedRoi | None
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Crop a frame and return both the image and full-frame pixel bounds."""

    if frame.ndim < 2 or frame.shape[0] <= 0 or frame.shape[1] <= 0:
        raise ValueError("frame must have a positive height and width")
    height, width = frame.shape[:2]
    if roi is None:
        return frame, (0, 0, width, height)

    x1_ratio, y1_ratio, x2_ratio, y2_ratio = roi
    x1 = int(round(width * x1_ratio))
    y1 = int(round(height * y1_ratio))
    x2 = int(round(width * x2_ratio))
    y2 = int(round(height * y2_ratio))
    x1 = min(max(x1, 0), width - 1)
    y1 = min(max(y1, 0), height - 1)
    x2 = min(max(x2, x1 + 1), width)
    y2 = min(max(y2, y1 + 1), height)
    return frame[y1:y2, x1:x2], (x1, y1, x2, y2)


def select_largest_pose(result: Any) -> SelectedPose | None:
    """Select the largest detected person.

    URFD is a single-person dataset, so the largest box is a simple and
    reproducible baseline. Multi-person scenes will use a tracker later.
    """

    if result.boxes is None or result.keypoints is None:
        return None

    boxes = result.boxes.xyxy.cpu().numpy()
    keypoints = result.keypoints.xy.cpu().numpy()
    if len(boxes) == 0 or len(keypoints) == 0:
        return None

    count = min(len(boxes), len(keypoints))
    boxes = boxes[:count]
    keypoints = keypoints[:count]
    areas = np.maximum(boxes[:, 2] - boxes[:, 0], 0) * np.maximum(
        boxes[:, 3] - boxes[:, 1], 0
    )
    person_index = int(np.argmax(areas))

    box_confidence = 0.0
    if result.boxes.conf is not None:
        box_confidence = float(result.boxes.conf[person_index].cpu().item())

    keypoint_confidence = np.ones(len(COCO_KEYPOINT_NAMES), dtype=float)
    if result.keypoints.conf is not None:
        keypoint_confidence = (
            result.keypoints.conf[person_index].cpu().numpy().astype(float)
        )

    return SelectedPose(
        person_index=person_index,
        bbox_xyxy=boxes[person_index].astype(float),
        bbox_confidence=box_confidence,
        keypoints_xy=keypoints[person_index].astype(float),
        keypoints_confidence=keypoint_confidence,
    )
