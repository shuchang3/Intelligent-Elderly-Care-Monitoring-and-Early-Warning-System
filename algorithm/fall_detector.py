"""Explainable temporal fall-detection baseline built on pose keypoints."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping

import numpy as np


LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_HIP = 11
RIGHT_HIP = 12


class FallState(str, Enum):
    NORMAL = "normal"
    FALLING = "falling"
    DOWN = "down"
    ALERTED = "alerted"


@dataclass(frozen=True)
class FallConfig:
    min_keypoint_confidence: float = 0.30
    downward_velocity_threshold: float = 0.25
    lying_aspect_ratio: float = 1.05
    horizontal_torso_angle_deg: float = 60.0
    minimum_bbox_bottom_normalized: float = 0.90
    velocity_window: int = 5
    falling_timeout_seconds: float = 1.20
    down_confirmation_seconds: float = 1.00
    recovery_seconds: float = 0.80
    missing_tolerance_seconds: float = 0.50

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "FallConfig":
        allowed = cls.__dataclass_fields__.keys()
        unknown = set(values) - set(allowed)
        if unknown:
            raise ValueError(f"Unknown fall detector keys: {sorted(unknown)}")
        config = cls(**values)
        if any(not math.isfinite(float(getattr(config, key))) or float(getattr(config, key)) <= 0 for key in allowed):
            raise ValueError("Fall detector thresholds must be positive")
        if not isinstance(config.velocity_window,int) or isinstance(config.velocity_window,bool) or config.velocity_window < 2:
            raise ValueError('velocity_window must be an integer >= 2')
        if (
            config.min_keypoint_confidence > 1
            or config.horizontal_torso_angle_deg > 90
            or config.minimum_bbox_bottom_normalized > 1
        ):
            raise ValueError('Normalized confidence/ground contact or torso angle out of range')
        return config


@dataclass(frozen=True)
class PoseFeatures:
    hip_y_normalized: float
    bbox_aspect_ratio: float
    torso_angle_deg: float
    mean_required_confidence: float
    bbox_bottom_normalized: float = 1.0


@dataclass(frozen=True)
class FallDecision:
    state: FallState
    event_started: bool
    downward_velocity: float
    is_lying: bool
    reason: str


def compute_pose_features(
    keypoints_xy: np.ndarray,
    keypoints_confidence: np.ndarray,
    bbox_xyxy: np.ndarray,
    frame_height: int,
    min_confidence: float,
) -> PoseFeatures | None:
    """Convert four stable torso keypoints and a box into explainable features."""

    required = np.array(
        [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP], dtype=int
    )
    if keypoints_xy.shape[0] <= int(required.max()):
        return None
    if keypoints_confidence.shape[0] <= int(required.max()):
        return None

    required_confidence = keypoints_confidence[required]
    if np.any(required_confidence < min_confidence):
        return None

    shoulder_midpoint = keypoints_xy[[LEFT_SHOULDER, RIGHT_SHOULDER]].mean(axis=0)
    hip_midpoint = keypoints_xy[[LEFT_HIP, RIGHT_HIP]].mean(axis=0)

    torso_dx = float(hip_midpoint[0] - shoulder_midpoint[0])
    torso_dy = float(hip_midpoint[1] - shoulder_midpoint[1])
    torso_angle = math.degrees(math.atan2(abs(torso_dx), max(abs(torso_dy), 1e-6)))

    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    width = max(x2 - x1, 1.0)
    height = max(y2 - y1, 1.0)

    return PoseFeatures(
        hip_y_normalized=float(hip_midpoint[1]) / max(frame_height, 1),
        bbox_aspect_ratio=width / height,
        torso_angle_deg=torso_angle,
        mean_required_confidence=float(required_confidence.mean()),
        bbox_bottom_normalized=min(max(y2 / max(frame_height, 1), 0.0), 1.0),
    )


class TemporalFallDetector:
    """State machine that requires rapid descent followed by a lying posture."""

    def __init__(self, config: FallConfig):
        self.config = config
        self.state = FallState.NORMAL
        self._hip_history: deque[tuple[float, float]] = deque(
            maxlen=max(config.velocity_window, 2)
        )
        self._fall_started_at: float | None = None
        self._down_started_at: float | None = None
        self._recovery_started_at: float | None = None
        self._last_seen_at: float | None = None
        self._rapid_motion_seen = False

    def reset(self) -> None:
        self.state = FallState.NORMAL
        self._hip_history.clear()
        self._fall_started_at = None
        self._down_started_at = None
        self._recovery_started_at = None
        self._last_seen_at = None
        self._rapid_motion_seen = False

    def update(
        self, features: PoseFeatures | None, timestamp_seconds: float
    ) -> FallDecision:
        if features is None:
            return self._handle_missing_pose(timestamp_seconds)

        self._last_seen_at = timestamp_seconds
        self._hip_history.append((timestamp_seconds, features.hip_y_normalized))
        downward_velocity = self._downward_velocity()
        is_lying = (
            features.bbox_bottom_normalized
            >= self.config.minimum_bbox_bottom_normalized
            and (
                features.bbox_aspect_ratio >= self.config.lying_aspect_ratio
                or features.torso_angle_deg >= self.config.horizontal_torso_angle_deg
            )
        )
        rapid_descent = downward_velocity >= self.config.downward_velocity_threshold
        event_started = False
        reason = "pose observed"

        if self.state == FallState.NORMAL:
            if rapid_descent:
                self._rapid_motion_seen = True
                self._fall_started_at = timestamp_seconds
                if is_lying:
                    self.state = FallState.DOWN
                    self._down_started_at = timestamp_seconds
                    reason = "rapid descent reached a lying posture"
                else:
                    self.state = FallState.FALLING
                    reason = "rapid downward hip movement"
            elif is_lying:
                # A horizontal pose alone is common while sitting, bending or
                # lying down. Keep observing until rapid descent is present;
                # otherwise DOWN would trap a later genuine fall candidate.
                reason = "lying posture ignored without rapid descent"

        elif self.state == FallState.FALLING:
            if is_lying:
                self.state = FallState.DOWN
                self._down_started_at = timestamp_seconds
                reason = "falling transition reached the ground"
            elif self._elapsed(self._fall_started_at, timestamp_seconds) > (
                self.config.falling_timeout_seconds
            ):
                self._return_to_normal(keep_history=True)
                reason = "falling candidate timed out"

        elif self.state == FallState.DOWN:
            if is_lying:
                self._recovery_started_at = None
                if (
                    self._rapid_motion_seen
                    and self._elapsed(self._down_started_at, timestamp_seconds)
                    >= self.config.down_confirmation_seconds
                ):
                    self.state = FallState.ALERTED
                    event_started = True
                    reason = "rapid descent followed by persistent lying"
            else:
                reason = self._update_recovery(timestamp_seconds)

        elif self.state == FallState.ALERTED:
            if is_lying:
                self._recovery_started_at = None
                reason = "fall alert remains active"
            else:
                reason = self._update_recovery(timestamp_seconds)

        return FallDecision(
            state=self.state,
            event_started=event_started,
            downward_velocity=downward_velocity,
            is_lying=is_lying,
            reason=reason,
        )

    def _downward_velocity(self) -> float:
        if len(self._hip_history) < 2:
            return 0.0
        first_time, first_y = self._hip_history[0]
        last_time, last_y = self._hip_history[-1]
        duration = last_time - first_time
        if duration <= 0:
            return 0.0
        return (last_y - first_y) / duration

    def _handle_missing_pose(self, timestamp_seconds: float) -> FallDecision:
        missing_for = self._elapsed(self._last_seen_at, timestamp_seconds)
        if missing_for > self.config.missing_tolerance_seconds:
            self.reset()
            reason = "pose missing beyond tolerance; candidate reset"
        else:
            reason = "brief pose miss"
        return FallDecision(
            state=self.state,
            event_started=False,
            downward_velocity=0.0,
            is_lying=False,
            reason=reason,
        )

    def _update_recovery(self, timestamp_seconds: float) -> str:
        if self._recovery_started_at is None:
            self._recovery_started_at = timestamp_seconds
            return "possible recovery started"
        if self._elapsed(self._recovery_started_at, timestamp_seconds) >= (
            self.config.recovery_seconds
        ):
            self._return_to_normal(keep_history=False)
            return "returned to normal after sustained recovery"
        return "waiting to confirm recovery"

    def _return_to_normal(self, keep_history: bool) -> None:
        self.state = FallState.NORMAL
        self._fall_started_at = None
        self._down_started_at = None
        self._recovery_started_at = None
        self._rapid_motion_seen = False
        if not keep_history:
            self._hip_history.clear()

    @staticmethod
    def _elapsed(start: float | None, end: float) -> float:
        return 0.0 if start is None else max(end - start, 0.0)

