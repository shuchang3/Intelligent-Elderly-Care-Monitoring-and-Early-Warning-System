import pytest

pytestmark = pytest.mark.ai
pytest.importorskip('numpy')

from algorithm.fall_detector import FallConfig, FallState, PoseFeatures, TemporalFallDetector


def pose(y: float, *, lying: bool = False, bottom: float = 1.0) -> PoseFeatures:
    return PoseFeatures(
        hip_y_normalized=y,
        bbox_aspect_ratio=1.2 if lying else 0.5,
        torso_angle_deg=75.0 if lying else 10.0,
        mean_required_confidence=0.9,
        bbox_bottom_normalized=bottom,
    )


def test_lying_without_rapid_descent_does_not_arm_fall():
    detector = TemporalFallDetector(FallConfig(down_confirmation_seconds=0.5))
    for timestamp in (0.0, 0.5, 1.0, 1.5):
        decision = detector.update(pose(0.6, lying=True), timestamp)
        assert decision.state == FallState.NORMAL
        assert not decision.event_started


def test_rapid_descent_then_sustained_lying_alerts_once():
    detector = TemporalFallDetector(
        FallConfig(
            velocity_window=2,
            downward_velocity_threshold=0.25,
            down_confirmation_seconds=0.5,
        )
    )
    detector.update(pose(0.2), 0.0)
    down = detector.update(pose(0.5, lying=True), 0.5)
    assert down.state == FallState.DOWN
    assert not down.event_started
    alert = detector.update(pose(0.55, lying=True), 1.0)
    assert alert.state == FallState.ALERTED
    assert alert.event_started
    assert not detector.update(pose(0.55, lying=True), 1.5).event_started


def test_missing_pose_beyond_tolerance_resets_candidate():
    detector = TemporalFallDetector(
        FallConfig(velocity_window=2, missing_tolerance_seconds=0.5)
    )
    detector.update(pose(0.2), 0.0)
    assert detector.update(pose(0.5), 0.5).state == FallState.FALLING
    decision = detector.update(None, 1.1)
    assert decision.state == FallState.NORMAL
    assert "reset" in decision.reason


def test_horizontal_pose_above_floor_is_not_a_fall():
    detector = TemporalFallDetector(
        FallConfig(
            velocity_window=2,
            downward_velocity_threshold=0.25,
            down_confirmation_seconds=0.5,
            minimum_bbox_bottom_normalized=0.9,
        )
    )
    detector.update(pose(0.2), 0.0)
    decision = detector.update(pose(0.5, lying=True, bottom=0.8), 0.5)
    assert decision.state == FallState.FALLING
    assert not detector.update(pose(0.55, lying=True, bottom=0.8), 1.0).event_started
