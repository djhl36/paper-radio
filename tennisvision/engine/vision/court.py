"""코트 검출 및 캘리브레이션.

두 가지 경로를 제공한다.

1. 수동(권장, 신뢰도 최상) — 앱에서 코트 4모서리를 탭하면 `calibrate_manual` 로
   호모그래피를 만든다. 실시간 심판 화면은 이 경로를 기본으로 쓴다.
2. 자동(`detect_court`) — 라인 픽셀 마스크 -> 허프 변환 -> 사각형 후보 ->
   코트 모델 재투영 점수로 최적 대응을 고른다. 카메라가 고정된 영상에서
   초기 추정을 자동으로 잡아주고, 사용자는 그 결과를 확인/수정만 하면 된다.
"""
from __future__ import annotations

import itertools
from typing import Optional, Sequence

import cv2
import numpy as np

from ..geometry import (
    CALIBRATION_ORDER,
    DOUBLES_HALF_W,
    HALF_LENGTH,
    LANDMARKS,
    LINE_SEGMENTS,
    SERVICE_LINE_Y,
    SINGLES_HALF_W,
    apply_homography,
    court_to_image,
    homography_from_points,
    reprojection_error,
)
from ..schema import Calibration


# --- 라인 픽셀 마스크 ------------------------------------------------------
def line_mask(frame: np.ndarray, width_px: int = 5, threshold: int = 20) -> np.ndarray:
    """코트 라인 픽셀 마스크.

    단순 밝기 임계값은 밝은 코트 표면/관중석에 무너진다. 대신 "라인은 자기
    좌우(또는 위아래)의 코트 표면보다 밝다"는 국소 대비 조건을 쓴다
    (Farin et al. 의 코트 라인 검출과 같은 아이디어).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    g = gray.astype(np.int16)
    d = max(2, int(width_px))

    # 수직 라인 후보: 좌우 이웃보다 밝다
    left = np.roll(g, d, axis=1)
    right = np.roll(g, -d, axis=1)
    vert = (g - left > threshold) & (g - right > threshold)
    vert[:, :d] = False
    vert[:, -d:] = False

    # 수평 라인 후보: 위아래 이웃보다 밝다
    up = np.roll(g, d, axis=0)
    down = np.roll(g, -d, axis=0)
    horz = (g - up > threshold) & (g - down > threshold)
    horz[:d, :] = False
    horz[-d:, :] = False

    mask = ((vert | horz) & (g > 90)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask


def _hough_lines(mask: np.ndarray, min_len_ratio: float = 0.12) -> np.ndarray:
    h, w = mask.shape[:2]
    min_len = int(min(h, w) * min_len_ratio)
    lines = cv2.HoughLinesP(
        mask, 1, np.pi / 360, threshold=60, minLineLength=min_len, maxLineGap=int(min_len * 0.6)
    )
    return lines.reshape(-1, 4) if lines is not None else np.zeros((0, 4), np.int32)


def _to_abc(x1, y1, x2, y2) -> tuple[float, float, float]:
    """두 점을 지나는 직선 ax+by+c=0 (정규화)."""
    a, b = y2 - y1, x1 - x2
    c = -(a * x1 + b * y1)
    n = float(np.hypot(a, b)) or 1.0
    return a / n, b / n, c / n


def _merge_lines(segs: np.ndarray, angle_tol_deg=3.0, dist_tol=18.0) -> list[tuple[float, float, float]]:
    """비슷한 직선들을 하나로 합친다."""
    merged: list[tuple[np.ndarray, float]] = []  # (누적 abc, 누적 길이)
    for x1, y1, x2, y2 in segs:
        abc = np.array(_to_abc(x1, y1, x2, y2))
        length = float(np.hypot(x2 - x1, y2 - y1))
        mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2, 1.0])
        placed = False
        for i, (acc, wsum) in enumerate(merged):
            cur = acc / wsum
            ang = np.degrees(np.arccos(np.clip(abs(cur[0] * abc[0] + cur[1] * abc[1]), 0, 1)))
            if ang < angle_tol_deg and abs(float(cur @ mid)) < dist_tol:
                sign = 1.0 if (cur[0] * abc[0] + cur[1] * abc[1]) >= 0 else -1.0
                merged[i] = (acc + sign * abc * length, wsum + length)
                placed = True
                break
        if not placed:
            merged.append((abc * length, length))
    out = []
    for acc, wsum in merged:
        v = acc / wsum
        n = float(np.hypot(v[0], v[1])) or 1.0
        out.append((float(v[0] / n), float(v[1] / n), float(v[2] / n)))
    return out


def _intersect(l1, l2) -> Optional[tuple[float, float]]:
    a1, b1, c1 = l1
    a2, b2, c2 = l2
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-8:
        return None
    x = (b1 * c2 - b2 * c1) / det
    y = (c1 * a2 - c2 * a1) / det
    return float(x), float(y)


def _model_support(H: np.ndarray, mask: np.ndarray, samples_per_seg: int = 40) -> float:
    """코트 모델 라인을 이미지에 재투영해서 라인 마스크와 얼마나 겹치는지 점수화."""
    h, w = mask.shape[:2]
    dil = cv2.dilate(mask, np.ones((7, 7), np.uint8))
    Hinv = np.linalg.inv(H)
    hits = total = 0
    for (p, q) in LINE_SEGMENTS:
        ts = np.linspace(0, 1, samples_per_seg)
        pts = np.stack([p[0] + (q[0] - p[0]) * ts, p[1] + (q[1] - p[1]) * ts], axis=1)
        img = apply_homography(Hinv, pts)
        for ix, iy in img:
            xi, yi = int(round(ix)), int(round(iy))
            if 0 <= xi < w and 0 <= yi < h:
                total += 1
                if dil[yi, xi] > 0:
                    hits += 1
    if total < samples_per_seg * 4:      # 코트가 화면 밖으로 너무 많이 나갔다
        return 0.0
    return hits / total


# --- 공개 API --------------------------------------------------------------
def calibrate_manual(
    image_points: Sequence[Sequence[float]],
    landmark_names: Sequence[str] = CALIBRATION_ORDER,
    frame_size: tuple[int, int] = (0, 0),
) -> Calibration:
    """사용자가 찍은 이미지 점 <-> 코트 랜드마크로 캘리브레이션.

    기본은 복식 코트 4모서리 (좌하 -> 우하 -> 우상 -> 좌상). 서비스라인 T 등
    추가 점을 더 주면 RANSAC 으로 정확도가 올라간다.
    """
    if len(image_points) != len(landmark_names):
        raise ValueError("이미지 점 개수와 랜드마크 이름 개수가 다릅니다")
    court_points = []
    for name in landmark_names:
        if name not in LANDMARKS:
            raise ValueError(f"알 수 없는 랜드마크: {name}")
        court_points.append(LANDMARKS[name])
    H = homography_from_points(image_points, court_points)
    err = reprojection_error(H, image_points, court_points)
    return Calibration(
        homography=H.tolist(),
        image_points=[(float(p[0]), float(p[1])) for p in image_points],
        court_points=[(float(c[0]), float(c[1])) for c in court_points],
        landmark_names=list(landmark_names),
        reprojection_error_m=err,
        method="manual",
        frame_size=tuple(frame_size),
    )


def detect_court(frame: np.ndarray, min_support: float = 0.45) -> Optional[Calibration]:
    """단일 프레임에서 코트를 자동 검출한다. 실패하면 None."""
    h, w = frame.shape[:2]
    mask = line_mask(frame)
    segs = _hough_lines(mask)
    if len(segs) < 4:
        return None
    lines = _merge_lines(segs)
    if len(lines) < 4:
        return None

    # 각도로 수평/수직 계열 분리 (a,b) 가 법선. |b| 큰 것이 수평선.
    horiz = [l for l in lines if abs(l[1]) > abs(l[0])]
    vert = [l for l in lines if abs(l[1]) <= abs(l[0])]
    if len(horiz) < 2 or len(vert) < 2:
        return None

    def y_at_center(l):
        a, b, c = l
        return -(a * (w / 2) + c) / (b if abs(b) > 1e-6 else 1e-6)

    def x_at_center(l):
        a, b, c = l
        return -(b * (h / 2) + c) / (a if abs(a) > 1e-6 else 1e-6)

    horiz.sort(key=y_at_center)
    vert.sort(key=x_at_center)

    # 후보: 바깥쪽 수평선 2개 x 바깥쪽 수직선 2개 조합 몇 가지
    h_cands = horiz[:2] + horiz[-2:]
    v_cands = vert[:2] + vert[-2:]

    # 모델 가설: 검출된 사각형이 (복식 코트) 또는 (단식 코트) 또는
    # (베이스라인 ~ 서비스라인) 인 경우를 모두 시도한다.
    hypotheses = [
        ("doubles", DOUBLES_HALF_W, HALF_LENGTH),
        ("singles", SINGLES_HALF_W, HALF_LENGTH),
    ]

    best: Optional[tuple[float, Calibration]] = None
    for hl in itertools.combinations(h_cands, 2):
        for vl in itertools.combinations(v_cands, 2):
            top, bot = sorted(hl, key=y_at_center)
            left, right = sorted(vl, key=x_at_center)
            corners = [
                _intersect(bot, left),    # 니어 좌
                _intersect(bot, right),   # 니어 우
                _intersect(top, right),   # 파 우
                _intersect(top, left),    # 파 좌
            ]
            if any(c is None for c in corners):
                continue
            pts = np.array(corners, dtype=np.float64)
            if cv2.contourArea(pts.astype(np.float32)) < 0.05 * w * h:
                continue
            for _, half_w, half_l in hypotheses:
                court_pts = [
                    (-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l)
                ]
                try:
                    H = homography_from_points(pts, court_pts)
                except ValueError:
                    continue
                support = _model_support(H, mask)
                if best is None or support > best[0]:
                    best = (
                        support,
                        Calibration(
                            homography=H.tolist(),
                            image_points=[(float(p[0]), float(p[1])) for p in pts],
                            court_points=[(float(c[0]), float(c[1])) for c in court_pts],
                            landmark_names=list(CALIBRATION_ORDER),
                            reprojection_error_m=reprojection_error(H, pts, court_pts),
                            method="auto",
                            frame_size=(w, h),
                        ),
                    )

    if best is None or best[0] < min_support:
        return None
    calib = best[1]
    # 자동 검출은 재투영 오차가 0에 가까워도(4점 정확해) 실제 정확도를 보장하지
    # 못한다. 모델 지지도를 오차로 환산해 보수적으로 기록한다.
    calib.reprojection_error_m = max(calib.reprojection_error_m, 0.25 * (1.0 - best[0]))
    return calib


def detect_court_stable(
    frames: Sequence[np.ndarray], min_support: float = 0.45
) -> Optional[Calibration]:
    """여러 프레임에서 검출해 가장 지지도 높은 결과를 고른다(사람/공 가림에 강함)."""
    best: Optional[Calibration] = None
    for f in frames:
        c = detect_court(f, min_support=min_support)
        if c is None:
            continue
        if best is None or c.reprojection_error_m < best.reprojection_error_m:
            best = c
    return best


def draw_overlay(frame: np.ndarray, calib: Calibration, color=(0, 220, 255), thickness=2) -> np.ndarray:
    """코트 모델을 프레임 위에 그린다(캘리브레이션 확인용)."""
    out = frame.copy()
    H = calib.H
    for (p, q) in LINE_SEGMENTS:
        p1 = court_to_image(H, *p)
        p2 = court_to_image(H, *q)
        cv2.line(out, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), color, thickness, cv2.LINE_AA)
    for name in ("near_center_service", "far_center_service"):
        x, y = LANDMARKS[name]
        ix, iy = court_to_image(H, x, y)
        cv2.circle(out, (int(ix), int(iy)), 4, (0, 0, 255), -1)
    return out


def court_polygon_image(calib: Calibration, doubles: bool = True) -> list[tuple[float, float]]:
    """앱 오버레이용: 코트 외곽 폴리곤의 이미지 좌표."""
    half_w = DOUBLES_HALF_W if doubles else SINGLES_HALF_W
    corners = [(-half_w, -HALF_LENGTH), (half_w, -HALF_LENGTH), (half_w, HALF_LENGTH), (-half_w, HALF_LENGTH)]
    return [court_to_image(calib.H, x, y) for x, y in corners]


def court_support(calib: Calibration, frame: np.ndarray) -> float:
    """이 프레임에서 코트 모델 라인이 실제 라인 픽셀과 얼마나 겹치는가 (0~1)."""
    return _model_support(calib.H, line_mask(frame))


def is_camera_moved(calib: Calibration, frame: np.ndarray, tolerance: float = 0.35) -> bool:
    """카메라가 흔들려 캘리브레이션이 깨졌는지 (절대 임계값 버전)."""
    return court_support(calib, frame) < tolerance


__all__ = [
    "line_mask",
    "calibrate_manual",
    "detect_court",
    "detect_court_stable",
    "draw_overlay",
    "court_polygon_image",
    "court_support",
    "is_camera_moved",
    "SERVICE_LINE_Y",
]
