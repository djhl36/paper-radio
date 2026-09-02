"""테니스 코트 기하 모델.

좌표계(코트 좌표, 단위 m):
    원점 = 네트 중앙, x = 코트 폭 방향, y = 코트 길이 방향, z = 높이.
    y < 0  : 니어 사이드(카메라에 가까운 쪽) 플레이어의 진영
    y > 0  : 파 사이드 플레이어의 진영
    니어 사이드 플레이어는 +y 를 바라보므로 그의 오른쪽(듀스 코트)은 x > 0,
    파 사이드 플레이어는 -y 를 바라보므로 그의 듀스 코트는 x < 0.
    (서브는 듀스 -> 듀스, 애드 -> 애드 대각선이 된다)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

import numpy as np

# --- ITF 규격 (m) ---------------------------------------------------------
HALF_LENGTH = 11.885          # 네트 ~ 베이스라인
SINGLES_HALF_W = 4.115        # 단식 사이드라인
DOUBLES_HALF_W = 5.485        # 복식 사이드라인
SERVICE_LINE_Y = 6.40         # 네트 ~ 서비스라인
NET_HEIGHT_CENTER = 0.914
NET_HEIGHT_POST = 1.07
BALL_RADIUS = 0.0335          # 공 반지름 6.7cm/2
LINE_WIDTH = 0.05             # 라인 폭 5cm (라인 바깥 모서리가 코트 경계)

Side = Literal["near", "far"]
CourtSide = Literal["deuce", "ad"]


def side_of(y: float) -> Side:
    return "near" if y < 0 else "far"


def opposite(side: Side) -> Side:
    return "far" if side == "near" else "near"


def facing_sign(side: Side) -> int:
    """해당 사이드 플레이어가 바라보는 y 방향."""
    return +1 if side == "near" else -1


def deuce_x_sign(side: Side) -> int:
    """해당 사이드 플레이어의 듀스 코트(오른쪽)가 놓인 x 부호."""
    return +1 if side == "near" else -1


# --- 코트 랜드마크 (호모그래피 대응점) -------------------------------------
LANDMARKS: dict[str, tuple[float, float]] = {
    # 복식 코너 (코트 4모서리)
    "near_left_doubles": (-DOUBLES_HALF_W, -HALF_LENGTH),
    "near_right_doubles": (DOUBLES_HALF_W, -HALF_LENGTH),
    "far_right_doubles": (DOUBLES_HALF_W, HALF_LENGTH),
    "far_left_doubles": (-DOUBLES_HALF_W, HALF_LENGTH),
    # 단식 코너
    "near_left_singles": (-SINGLES_HALF_W, -HALF_LENGTH),
    "near_right_singles": (SINGLES_HALF_W, -HALF_LENGTH),
    "far_right_singles": (SINGLES_HALF_W, HALF_LENGTH),
    "far_left_singles": (-SINGLES_HALF_W, HALF_LENGTH),
    # 서비스 라인 교차점
    "near_left_service": (-SINGLES_HALF_W, -SERVICE_LINE_Y),
    "near_right_service": (SINGLES_HALF_W, -SERVICE_LINE_Y),
    "far_right_service": (SINGLES_HALF_W, SERVICE_LINE_Y),
    "far_left_service": (-SINGLES_HALF_W, SERVICE_LINE_Y),
    # 센터 서비스 라인 T 지점
    "near_center_service": (0.0, -SERVICE_LINE_Y),
    "far_center_service": (0.0, SERVICE_LINE_Y),
    # 베이스라인 센터 마크
    "near_center_mark": (0.0, -HALF_LENGTH),
    "far_center_mark": (0.0, HALF_LENGTH),
    # 네트 라인(지면 투영)
    "net_left": (-DOUBLES_HALF_W, 0.0),
    "net_right": (DOUBLES_HALF_W, 0.0),
}

# 앱의 수동 캘리브레이션(4점 탭)에서 요구하는 순서
CALIBRATION_ORDER = (
    "near_left_doubles",
    "near_right_doubles",
    "far_right_doubles",
    "far_left_doubles",
)

# 코트 라인 세그먼트 (자동 캘리브레이션 검증 및 오버레이 렌더용)
LINE_SEGMENTS: tuple[tuple[tuple[float, float], tuple[float, float]], ...] = (
    ((-DOUBLES_HALF_W, -HALF_LENGTH), (DOUBLES_HALF_W, -HALF_LENGTH)),
    ((-DOUBLES_HALF_W, HALF_LENGTH), (DOUBLES_HALF_W, HALF_LENGTH)),
    ((-DOUBLES_HALF_W, -HALF_LENGTH), (-DOUBLES_HALF_W, HALF_LENGTH)),
    ((DOUBLES_HALF_W, -HALF_LENGTH), (DOUBLES_HALF_W, HALF_LENGTH)),
    ((-SINGLES_HALF_W, -HALF_LENGTH), (-SINGLES_HALF_W, HALF_LENGTH)),
    ((SINGLES_HALF_W, -HALF_LENGTH), (SINGLES_HALF_W, HALF_LENGTH)),
    ((-SINGLES_HALF_W, -SERVICE_LINE_Y), (SINGLES_HALF_W, -SERVICE_LINE_Y)),
    ((-SINGLES_HALF_W, SERVICE_LINE_Y), (SINGLES_HALF_W, SERVICE_LINE_Y)),
    ((0.0, -SERVICE_LINE_Y), (0.0, SERVICE_LINE_Y)),
    ((-DOUBLES_HALF_W, 0.0), (DOUBLES_HALF_W, 0.0)),
)


# --- 판정 영역 -------------------------------------------------------------
@dataclass(frozen=True)
class Region:
    """축 정렬 사각형 판정 영역. 경계는 라인 바깥 모서리 기준."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def signed_margin(self, x: float, y: float) -> float:
        """영역 경계까지의 부호 있는 거리(m).

        양수 = 안쪽으로 얼마나 들어왔는가, 음수 = 밖으로 얼마나 나갔는가.
        """
        dx = min(x - self.x_min, self.x_max - x)
        dy = min(y - self.y_min, self.y_max - y)
        if dx >= 0 and dy >= 0:
            return float(min(dx, dy))
        ox = max(self.x_min - x, 0.0, x - self.x_max)
        oy = max(self.y_min - y, 0.0, y - self.y_max)
        return -float(np.hypot(ox, oy))

    def contains(self, x: float, y: float) -> bool:
        return self.signed_margin(x, y) >= 0.0

    def nearest_line(self, x: float, y: float) -> str:
        """가장 가까운 경계선 이름 (판정 설명용)."""
        cands = {
            "left": abs(x - self.x_min),
            "right": abs(self.x_max - x),
            "near": abs(y - self.y_min),
            "far": abs(self.y_max - y),
        }
        return min(cands, key=cands.get)


def rally_region(receiver_side: Side, doubles: bool = False) -> Region:
    """랠리 중 유효 영역(상대 진영 전체)."""
    half_w = DOUBLES_HALF_W if doubles else SINGLES_HALF_W
    if receiver_side == "far":
        return Region("far_court", -half_w, half_w, 0.0, HALF_LENGTH)
    return Region("near_court", -half_w, half_w, -HALF_LENGTH, 0.0)


def service_box(receiver_side: Side, court: CourtSide) -> Region:
    """리시버 진영의 듀스/애드 서비스 박스."""
    sign = deuce_x_sign(receiver_side) if court == "deuce" else -deuce_x_sign(receiver_side)
    x_lo, x_hi = (0.0, SINGLES_HALF_W) if sign > 0 else (-SINGLES_HALF_W, 0.0)
    if receiver_side == "far":
        return Region(f"far_{court}_box", x_lo, x_hi, 0.0, SERVICE_LINE_Y)
    return Region(f"near_{court}_box", x_lo, x_hi, -SERVICE_LINE_Y, 0.0)


def serve_target_box(server_side: Side, court: CourtSide) -> Region:
    """서버 사이드/코트에서 서브가 들어가야 하는 박스."""
    return service_box(opposite(server_side), court)


def serve_position(server_side: Side, court: CourtSide) -> tuple[float, float]:
    """서버가 서 있어야 하는 대략 위치(오버레이/검증용)."""
    sign = deuce_x_sign(server_side) if court == "deuce" else -deuce_x_sign(server_side)
    x = sign * SINGLES_HALF_W * 0.45
    y = -HALF_LENGTH if server_side == "near" else HALF_LENGTH
    return (x, y)


def serve_zone(x: float, y: float, server_side: Side, court: CourtSide) -> str:
    """서브 코스 분류: T / body / wide."""
    box = serve_target_box(server_side, court)
    # 센터 서비스 라인(x=0)에서 사이드라인까지를 3등분한다
    inner, outer = (box.x_min, box.x_max) if abs(box.x_min) < abs(box.x_max) else (box.x_max, box.x_min)
    t = abs(x - inner) / max(abs(outer - inner), 1e-6)
    if t < 0.33:
        return "T"
    if t < 0.66:
        return "body"
    return "wide"


# --- 호모그래피 유틸 -------------------------------------------------------
def homography_from_points(
    image_pts: Sequence[Sequence[float]], court_pts: Sequence[Sequence[float]]
) -> np.ndarray:
    """이미지 좌표 -> 코트 좌표 호모그래피 (최소 4점)."""
    import cv2

    src = np.asarray(image_pts, dtype=np.float64).reshape(-1, 1, 2)
    dst = np.asarray(court_pts, dtype=np.float64).reshape(-1, 1, 2)
    if len(src) < 4:
        raise ValueError("호모그래피에는 최소 4개의 대응점이 필요합니다")
    method = 0 if len(src) == 4 else cv2.RANSAC
    H, _ = cv2.findHomography(src, dst, method, 3.0)
    if H is None:
        raise ValueError("호모그래피 계산 실패 (점이 일직선이거나 대응이 잘못됨)")
    return H


def apply_homography(H: np.ndarray, pts: Iterable[Sequence[float]]) -> np.ndarray:
    """(N,2) 점들을 호모그래피로 변환."""
    p = np.asarray(list(pts), dtype=np.float64).reshape(-1, 2)
    ones = np.ones((len(p), 1))
    hom = np.hstack([p, ones]) @ H.T
    w = hom[:, 2:3].copy()
    w[np.abs(w) < 1e-12] = 1e-12
    return hom[:, :2] / w


def image_to_court(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    out = apply_homography(H, [(x, y)])[0]
    return float(out[0]), float(out[1])


def court_to_image(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    Hinv = np.linalg.inv(H)
    out = apply_homography(Hinv, [(x, y)])[0]
    return float(out[0]), float(out[1])


def reprojection_error(
    H: np.ndarray,
    image_pts: Sequence[Sequence[float]],
    court_pts: Sequence[Sequence[float]],
) -> float:
    """캘리브레이션 품질 지표: 코트 좌표계에서의 평균 오차(m)."""
    pred = apply_homography(H, image_pts)
    gt = np.asarray(court_pts, dtype=np.float64).reshape(-1, 2)
    return float(np.mean(np.linalg.norm(pred - gt, axis=1)))


def meters_per_pixel(H: np.ndarray, ix: float, iy: float) -> float:
    """이미지 (ix,iy) 근방에서 1px 이 코트 좌표로 몇 m 인지.

    원근 때문에 위치마다 다르므로 판정 오차 예산은 반드시 바운스 지점에서 계산한다.
    """
    p0 = np.array(image_to_court(H, ix, iy))
    p1 = np.array(image_to_court(H, ix + 1.0, iy))
    p2 = np.array(image_to_court(H, ix, iy + 1.0))
    return float(0.5 * (np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p0)))
