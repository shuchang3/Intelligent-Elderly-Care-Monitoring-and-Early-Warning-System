import pytest

pytestmark = pytest.mark.ai
np = pytest.importorskip('numpy')

from algorithm.pose_utils import box_iou, match_boxes_one_to_one


def test_box_iou_handles_overlap_and_empty_boxes():
    assert box_iou(np.array([0, 0, 10, 10]), np.array([5, 5, 15, 15])) == 25 / 175
    assert box_iou(np.array([0, 0, 0, 0]), np.array([0, 0, 1, 1])) == 0


def test_pose_assignment_is_unique_and_prefers_strongest_overlap():
    tracks = [np.array([0, 0, 10, 10]), np.array([4, 0, 14, 10])]
    poses = np.array([[3, 0, 13, 10], [0, 0, 9, 10]], dtype=float)

    assignments = match_boxes_one_to_one(tracks, poses, minimum_iou=0.3)

    assert assignments == {0: 1, 1: 0}
    assert len(set(assignments.values())) == len(assignments)


def test_pose_assignment_rejects_weak_overlap():
    assignments = match_boxes_one_to_one(
        [np.array([0, 0, 10, 10])], np.array([[20, 20, 30, 30]]), 0.3
    )
    assert assignments == {}
