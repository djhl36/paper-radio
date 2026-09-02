"""플레이어 검출/추적.

기본 구현은 배경 차분(MOG2) 기반이다. 삼각대 고정 촬영을 전제로 하며, 큰
전경 블롭의 하단 중앙을 발 위치로 보고 호모그래피로 코트 좌표에 올린다.
코트 좌표로 올린 뒤 y 부호로 니어/파 사이드에 배정하기 때문에, 관중이나
심판처럼 코트 밖에 있는 블롭은 자연스럽게 걸러진다.

YOLO 가 설치돼 있으면 `detectors.use("player", "yolo")` 로 교체 가능하고,
아래 `PlayerTracker` 는 검출기 종류와 무관하게 동작한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np

from ..geometry import DOUBLES_HALF_W, HALF_LENGTH, image_to_court
from ..schema import Calibration, Detection, PlayerTrack, Side
from . import detectors


@dataclass
class MotionPlayerConfig:
    min_area_ratio: float = 0.0008     # 프레임 면적 대비 최소 블롭 크기
    max_area_ratio: float = 0.10
    min_aspect: float = 0.9            # 사람은 세로로 길다 (h/w)
    history: int = 300
    var_threshold: float = 32.0


class MotionPlayerDetector:
    """MOG2 배경 차분 기반 사람 블롭 검출기."""

    def __init__(self, **kw):
        self.cfg = MotionPlayerConfig(**kw)
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=self.cfg.history, varThreshold=self.cfg.var_threshold, detectShadows=True
        )
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 9))

    def detect(self, frame: np.ndarray, frame_index: int) -> list[Detection]:
        fg = self.bg.apply(frame)
        fg[fg < 200] = 0                                  # 그림자(127) 제거
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel, iterations=2)
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = frame.shape[:2]
        area = h * w
        out: list[Detection] = []
        for c in contours:
            a = cv2.contourArea(c)
            if a < area * self.cfg.min_area_ratio or a > area * self.cfg.max_area_ratio:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw <= 0 or bh / bw < self.cfg.min_aspect:
                continue
            out.append(
                Detection(
                    frame=frame_index, x=float(x + bw / 2), y=float(y + bh),
                    confidence=float(min(1.0, a / (area * 0.01))), w=float(bw), h=float(bh),
                    source="motion",
                )
            )
        out.sort(key=lambda d: -(d.w * d.h))
        return out[:8]


detectors.register_player_detector("motion", MotionPlayerDetector)


class PlayerTracker:
    """니어/파 각 1명을 유지하는 추적기 (단식 기준)."""

    def __init__(self, calibration: Calibration, detector=None, doubles: bool = False,
                 margin_m: float = 3.0, smoothing: float = 0.6):
        self.calib = calibration
        self.detector = detector or detectors.make_player_detector()
        self.doubles = doubles
        self.margin = margin_m
        self.alpha = smoothing
        self.tracks: dict[Side, PlayerTrack] = {
            "near": PlayerTrack(side="near"),
            "far": PlayerTrack(side="far"),
        }
        self._last: dict[Side, Optional[tuple[float, float]]] = {"near": None, "far": None}

    def _in_play_area(self, cx: float, cy: float) -> bool:
        half_w = (DOUBLES_HALF_W if self.doubles else DOUBLES_HALF_W) + self.margin
        return abs(cx) <= half_w and abs(cy) <= HALF_LENGTH + self.margin

    def update(self, frame: np.ndarray, frame_index: int) -> dict[Side, Optional[tuple[float, float]]]:
        dets = self.detector.detect(frame, frame_index)
        H = self.calib.H
        by_side: dict[Side, list[tuple[float, Detection, tuple[float, float]]]] = {"near": [], "far": []}
        for d in dets:
            cx, cy = image_to_court(H, d.x, d.y)
            if not self._in_play_area(cx, cy):
                continue
            side: Side = "near" if cy < 0 else "far"
            prev = self._last[side]
            # 이전 위치에 가깝고 큰 블롭을 선호
            dist = 0.0 if prev is None else float(np.hypot(cx - prev[0], cy - prev[1]))
            score = d.w * d.h * (1.0 / (1.0 + 0.25 * dist))
            by_side[side].append((score, d, (cx, cy)))

        result: dict[Side, Optional[tuple[float, float]]] = {}
        for side in ("near", "far"):
            track = self.tracks[side]
            while len(track.positions) < frame_index:
                track.positions.append(None)
                track.court_positions.append(None)
            if by_side[side]:
                _, d, court = max(by_side[side], key=lambda s: s[0])
                prev = self._last[side]
                if prev is not None:
                    court = (
                        self.alpha * court[0] + (1 - self.alpha) * prev[0],
                        self.alpha * court[1] + (1 - self.alpha) * prev[1],
                    )
                self._last[side] = court
                track.positions.append((d.x, d.y))
                track.court_positions.append(court)
                result[side] = court
            else:
                track.positions.append(None)
                track.court_positions.append(self._last[side])
                result[side] = self._last[side]
        return result

    def run(self, frames: Iterable[np.ndarray]) -> dict[Side, PlayerTrack]:
        for i, frame in enumerate(frames):
            self.update(frame, i)
        return self.tracks


def nearest_player_side(
    court_xy: tuple[float, float], positions: dict[Side, Optional[tuple[float, float]]]
) -> Optional[Side]:
    """어떤 지점에서 가장 가까운 플레이어의 사이드."""
    best: Optional[tuple[float, Side]] = None
    for side, p in positions.items():
        if p is None:
            continue
        d = float(np.hypot(court_xy[0] - p[0], court_xy[1] - p[1]))
        if best is None or d < best[0]:
            best = (d, side)  # type: ignore[assignment]
    return best[1] if best else None


def coverage_metrics(track: PlayerTrack, fps: float) -> dict:
    """이동 거리, 평균 위치, 복귀 성실도 등 움직임 지표."""
    pts = [p for p in track.court_positions if p is not None]
    if len(pts) < 2:
        return {"distance_m": 0.0, "avg_x": 0.0, "avg_depth_m": 0.0, "recovery_score": 0.0}
    arr = np.asarray(pts, dtype=np.float64)
    steps = np.linalg.norm(np.diff(arr, axis=0), axis=1)
    steps = steps[steps < 1.5]                    # 검출 튐 제거 (프레임당 1.5m 이상은 노이즈)
    dist = float(steps.sum())
    avg_x = float(arr[:, 0].mean())
    depth = float(np.abs(np.abs(arr[:, 1]) - HALF_LENGTH).mean())
    # 복귀 성실도: 중앙(x=0)에 얼마나 자주 돌아오는가
    recovery = float(np.mean(np.abs(arr[:, 0]) < 1.5))
    return {
        "distance_m": round(dist, 1),
        "avg_x": round(avg_x, 2),
        "avg_depth_m": round(depth, 2),
        "recovery_score": round(recovery, 3),
        "seconds": round(len(pts) / max(fps, 1e-6), 1),
    }


__all__ = [
    "MotionPlayerDetector",
    "PlayerTracker",
    "nearest_player_side",
    "coverage_metrics",
]
