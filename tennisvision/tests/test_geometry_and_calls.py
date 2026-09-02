"""코트 기하 · 캘리브레이션 · 인아웃 판정 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.geometry import (  # noqa: E402
    DOUBLES_HALF_W,
    HALF_LENGTH,
    LANDMARKS,
    SERVICE_LINE_Y,
    SINGLES_HALF_W,
    image_to_court,
    rally_region,
    serve_target_box,
    serve_zone,
)
from engine.schema import BallTrack  # noqa: E402
from engine.umpire.inout import judge_point  # noqa: E402
from engine.vision.court import calibrate_manual  # noqa: E402

CORNERS = ["near_left_doubles", "near_right_doubles", "far_right_doubles", "far_left_doubles"]
# 임의의 사다리꼴(원근이 있는 가상 카메라)
IMAGE_PTS = [[182.4, 682.7], [1066.8, 694.6], [780.7, 275.8], [510.4, 274.7]]


def test_serve_boxes_are_diagonal():
    """니어 듀스에서 넣으면 파 사이드의 x<0 박스로 가야 한다(대각)."""
    box = serve_target_box("near", "deuce")
    assert box.y_min >= 0 and box.y_max == SERVICE_LINE_Y
    assert box.x_max <= 0, "니어 듀스 서브는 파 선수의 오른쪽(=x<0) 박스로 간다"

    box_ad = serve_target_box("near", "ad")
    assert box_ad.x_min >= 0

    far_box = serve_target_box("far", "deuce")
    assert far_box.y_max <= 0 and far_box.x_min >= 0


def test_service_boxes_do_not_overlap():
    a = serve_target_box("near", "deuce")
    b = serve_target_box("near", "ad")
    assert a.x_max <= b.x_min or b.x_max <= a.x_min


def test_region_margin_sign():
    r = rally_region("far")
    assert r.signed_margin(0, 5) > 0
    assert r.signed_margin(0, HALF_LENGTH + 0.5) < 0
    assert abs(r.signed_margin(0, HALF_LENGTH)) < 1e-9
    # 코너 바깥은 유클리드 거리
    m = r.signed_margin(SINGLES_HALF_W + 0.3, HALF_LENGTH + 0.4)
    assert abs(m + np.hypot(0.3, 0.4)) < 1e-9


def test_serve_zone_classification():
    assert serve_zone(-0.3, 4.0, "near", "deuce") == "T"
    assert serve_zone(-3.9, 4.0, "near", "deuce") == "wide"
    assert serve_zone(-2.0, 4.0, "near", "deuce") == "body"


def test_homography_round_trip():
    calib = calibrate_manual(IMAGE_PTS, CORNERS, frame_size=(1280, 720))
    assert calib.reprojection_error_m < 1e-4      # 0.1mm 이하
    for name, img_pt in zip(CORNERS, IMAGE_PTS):
        got = image_to_court(calib.H, *img_pt)
        want = LANDMARKS[name]
        assert np.allclose(got, want, atol=1e-4)


def test_calibration_quality_levels():
    calib = calibrate_manual(IMAGE_PTS, CORNERS)
    assert calib.quality() == "excellent"
    calib.reprojection_error_m = 0.12
    assert calib.quality() == "fair"
    calib.reprojection_error_m = 0.5
    assert calib.quality() == "poor"


def _dummy_track() -> BallTrack:
    return BallTrack(positions=[(100.0, 100.0)] * 5, confidence=[1.0] * 5, fps=30.0)


def test_ball_touching_line_is_in():
    """공이 라인에 걸치기만 해도 인. 중심이 라인 밖 3cm 여도 반지름 3.35cm 라 인."""
    region = rally_region("far")
    x = 0.0
    y = HALF_LENGTH + 0.03
    call = judge_point((x, y), (100, 100), region, error_budget_cm=1.0, frame=0, t=0.0)
    assert call.kind == "in"
    assert call.margin_cm > 0


def test_clearly_out_is_out():
    region = rally_region("far")
    call = judge_point((0.0, HALF_LENGTH + 0.4), (100, 100), region, 2.0, 0, 0.0)
    assert call.kind == "out"
    assert call.margin_cm < -30
    assert call.confidence > 0.99
    assert not call.too_close


def test_too_close_when_inside_error_budget():
    region = rally_region("far")
    # 라인에서 1cm, 오차 예산 8cm -> 판독 불가여야 한다
    call = judge_point((0.0, HALF_LENGTH - 0.0235), (100, 100), region, 8.0, 0, 0.0)
    assert call.too_close
    assert 0.4 < call.confidence < 0.95


def test_serve_out_is_called_fault():
    box = serve_target_box("near", "deuce")
    call = judge_point((-2.0, SERVICE_LINE_Y + 0.6), (10, 10), box, 2.0, 0, 0.0, is_serve=True)
    assert call.kind == "fault"


def test_confidence_grows_with_margin():
    region = rally_region("far")
    near_line = judge_point((0.0, HALF_LENGTH + 0.05), (0, 0), region, 5.0, 0, 0.0)
    far_out = judge_point((0.0, HALF_LENGTH + 0.6), (0, 0), region, 5.0, 0, 0.0)
    assert far_out.confidence > near_line.confidence


def test_doubles_region_is_wider():
    singles = rally_region("far", doubles=False)
    doubles = rally_region("far", doubles=True)
    x = (SINGLES_HALF_W + DOUBLES_HALF_W) / 2
    assert not singles.contains(x, 5.0)
    assert doubles.contains(x, 5.0)
