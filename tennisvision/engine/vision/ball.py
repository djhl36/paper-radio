"""공 검출 및 추적 (가중치 없이 동작하는 기본 구현).

핵심 아이디어
- 테니스공은 화면에서 가장 빠르게 움직이는 아주 작은 물체다. 3프레임 차분의
  교집합을 쓰면 배경/느린 물체/그림자를 대부분 지우고 공과 라켓만 남는다.
- 남은 후보 중에서 (a) 크기가 공에 맞고 (b) 원형에 가깝고 (c) 테니스공 색이
  잡히는 것을 고른다. 등속 예측은 '물리적으로 불가능한 점프'를 막는 데만 쓴다.
- 놓친 프레임은 그대로 비워 둔다. 이벤트 검출은 결측 구간을 건너뛰며 창을
  채우므로, 억지 보간으로 가짜 꺾임을 만드는 것보다 비워 두는 편이 안전하다.
  (`interpolate_track` 은 화면 표시용 궤적에만 쓴다)

정확도가 더 필요하면 `detectors.use("ball", "tracknet", weights=...)` 로
딥러닝 검출기를 꽂는다. 아래 추적/보간 로직은 그대로 재사용된다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Sequence

import cv2
import numpy as np

from ..schema import BallTrack, Detection
from . import detectors


# --- 후보 검출 -------------------------------------------------------------
@dataclass
class BallDetectorConfig:
    diff_threshold: int = 12
    min_radius_px: float = 1.0
    max_radius_px: float = 14.0
    min_circularity: float = 0.25
    max_candidates: int = 12
    use_color_prior: bool = True
    hsv_low: tuple = (22, 55, 100)
    hsv_high: tuple = (48, 255, 255)


class MotionBallDetector:
    """3프레임 차분 기반 공 후보 검출기 (lag = 1)."""

    def __init__(self, **kw):
        self.cfg = BallDetectorConfig(**kw)
        self._frames: deque[np.ndarray] = deque(maxlen=3)
        self._raw: deque[np.ndarray] = deque(maxlen=3)

    @property
    def lag(self) -> int:
        return 1

    def reset(self) -> None:
        self._frames.clear()
        self._raw.clear()

    def push(self, frame: np.ndarray, frame_index: int) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        self._frames.append(gray)
        self._raw.append(frame)
        if len(self._frames) < 3:
            return []
        f0, f1, f2 = self._frames
        target_index = frame_index - self.lag
        return self._candidates(f0, f1, f2, self._raw[1], target_index)

    def _candidates(self, f0, f1, f2, color_frame, frame_index: int) -> list[Detection]:
        cfg = self.cfg
        d1 = cv2.absdiff(f1, f0)
        d2 = cv2.absdiff(f1, f2)
        _, t1 = cv2.threshold(d1, cfg.diff_threshold, 255, cv2.THRESH_BINARY)
        _, t2 = cv2.threshold(d2, cfg.diff_threshold, 255, cv2.THRESH_BINARY)
        motion = cv2.bitwise_and(t1, t2)
        motion = cv2.morphologyEx(motion, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        motion = cv2.dilate(motion, np.ones((3, 3), np.uint8))

        contours, _ = cv2.findContours(motion, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        color_mask = self._color_mask(color_frame) if cfg.use_color_prior else None

        out: list[Detection] = []
        min_a = np.pi * cfg.min_radius_px ** 2
        max_a = np.pi * cfg.max_radius_px ** 2
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_a or area > max_a:
                continue
            (cx, cy), r = cv2.minEnclosingCircle(c)
            if r <= 0:
                continue
            circularity = area / (np.pi * r * r)
            if circularity < cfg.min_circularity:
                continue
            color = 0.0
            if color_mask is not None:
                yi, xi = int(cy), int(cx)
                h, w = color_mask.shape
                y0, y1_ = max(0, yi - 3), min(h, yi + 4)
                x0, x1_ = max(0, xi - 3), min(w, xi + 4)
                patch = color_mask[y0:y1_, x0:x1_]
                if patch.size:
                    color = float(patch.mean() / 255.0)
            score = 0.25 + 0.35 * circularity + 0.40 * min(color * 2.5, 1.0)
            out.append(
                Detection(
                    frame=frame_index, x=float(cx), y=float(cy),
                    confidence=float(min(score, 1.0)), w=2 * r, h=2 * r, source="motion",
                    color_support=round(min(color * 2.5, 1.0), 3),
                )
            )
        out.sort(key=lambda d: -d.confidence)
        return out[: cfg.max_candidates]

    def _color_mask(self, frame: np.ndarray) -> np.ndarray:
        """테니스공의 형광 옐로우-그린 영역."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, np.array(self.cfg.hsv_low, np.uint8),
                           np.array(self.cfg.hsv_high, np.uint8))


detectors.register_ball_detector("motion", MotionBallDetector)


# --- 추적 ------------------------------------------------------------------
@dataclass
class TrackerConfig:
    base_gate_px: float = 120.0        # 넉넉히 — 게이트는 '말도 안 되는 점프'만 막는다
    velocity_gate_factor: float = 2.5
    max_missing: int = 12
    color_mode: str = "auto"           # auto | require | prefer | off
    min_color_support: float = 0.25
    color_auto_threshold: float = 0.25  # 이 비율 이상 색이 잡히면 require 로 승격
    color_warmup_frames: int = 90


class BallTracker:
    """공 후보 중 하나를 골라 궤적을 만든다.

    실측해 보면 후보 검출기의 1순위 후보가 실제 공인 경우가 압도적이라(99%+),
    예측-게이팅으로 후보를 걸러 내는 것보다 **오검출을 확실히 죽이는 쪽**이
    훨씬 이득이다. 그래서 이 추적기는

      1) 테니스공 색(형광 옐로우-그린)이 잡히는 영상에서는 색 지지도가 없는
         후보를 아예 버리고 (선수 옷/그림자 가장자리가 여기서 전멸한다),
      2) 남은 후보 중 점수 1위를 고르되,
      3) 게이트는 직전 궤적에서 물리적으로 불가능한 점프만 막는 데 쓴다.

    색이 거의 안 잡히는 영상(야간/저화질/흰 공)에서는 자동으로 색 조건을
    풀어서 예전 방식으로 동작한다.
    """

    def __init__(self, detector=None, **kw):
        self.cfg = TrackerConfig(**kw)
        self.detector = detector or detectors.make_ball_detector()
        self.history: deque[tuple[int, float, float]] = deque(maxlen=8)
        self.missing = 0
        self.active = False
        self._results: dict[int, tuple[float, float, float]] = {}
        self._last_index = -1
        self._frames_with_cands = 0
        self._frames_with_color = 0
        self._color_required: Optional[bool] = None

    def reset(self) -> None:
        self.detector.reset()
        self.history.clear()
        self.missing = 0
        self.active = False
        self._results.clear()
        self._last_index = -1
        self._frames_with_cands = 0
        self._frames_with_color = 0
        self._color_required = None

    # 색 조건 판단 -----------------------------------------------------------
    def _color_filter(self, cands: Sequence[Detection]) -> list[Detection]:
        mode = self.cfg.color_mode
        if mode == "off":
            return list(cands)
        colored = [c for c in cands if c.color_support >= self.cfg.min_color_support]
        if cands:
            self._frames_with_cands += 1
            if colored:
                self._frames_with_color += 1
        if mode == "require":
            return colored
        if mode == "prefer":
            return colored or list(cands)
        # auto: 워밍업 동안 통계를 모아 결정한다
        if self._color_required is None:
            if self._frames_with_cands >= self.cfg.color_warmup_frames:
                ratio = self._frames_with_color / max(self._frames_with_cands, 1)
                self._color_required = ratio >= self.cfg.color_auto_threshold
            return colored or list(cands)
        return colored if self._color_required else list(cands)

    @property
    def color_required(self) -> bool:
        return bool(self._color_required)

    # 예측 -----------------------------------------------------------------
    def _predict(self, frame_index: int) -> Optional[tuple[float, float]]:
        if len(self.history) < 2:
            if self.history:
                return self.history[-1][1], self.history[-1][2]
            return None
        (f1, x1, y1), (f0, x0, y0) = self.history[-1], self.history[-2]
        dt = max(f1 - f0, 1)
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        step = frame_index - f1
        return x1 + vx * step, y1 + vy * step

    def _speed(self) -> float:
        if len(self.history) < 2:
            return 0.0
        (f1, x1, y1), (f0, x0, y0) = self.history[-1], self.history[-2]
        return float(np.hypot(x1 - x0, y1 - y0) / max(f1 - f0, 1))

    # 갱신 -----------------------------------------------------------------
    def update(self, frame: np.ndarray, frame_index: int) -> Optional[Detection]:
        """프레임 1장을 넣고, 확정된 (frame_index - lag) 프레임의 공 위치를 받는다."""
        cands = self.detector.push(frame, frame_index)
        target = frame_index - getattr(self.detector, "lag", 1)
        if target < 0:
            return None
        self._last_index = max(self._last_index, target)
        best = self._select(cands, target)
        if best is None:
            self.missing += 1
            if self.missing > self.cfg.max_missing:
                self.active = False
                self.history.clear()
            return None
        self.missing = 0
        self.active = True
        self.history.append((target, best.x, best.y))
        self._results[target] = (best.x, best.y, best.confidence)
        return best

    def to_track(self, length: int, fps: float) -> BallTrack:
        """추적 결과를 길이 length 의 BallTrack 으로 만든다(결측은 None)."""
        positions: list[Optional[tuple[float, float]]] = [None] * length
        conf = [0.0] * length
        for f, (x, y, c) in self._results.items():
            if 0 <= f < length:
                positions[f] = (x, y)
                conf[f] = c
        return BallTrack(positions=positions, confidence=conf, fps=fps)

    def position_at(self, frame: int) -> Optional[tuple[float, float]]:
        """확정된 프레임의 공 위치 (없으면 None)."""
        r = self._results.get(frame)
        return (r[0], r[1]) if r else None

    def confidence_at(self, frame: int) -> float:
        r = self._results.get(frame)
        return r[2] if r else 0.0

    def _select(self, cands: Sequence[Detection], frame_index: int) -> Optional[Detection]:
        allowed = self._color_filter(cands)
        if not allowed:
            return None
        best = max(allowed, key=lambda d: d.confidence)
        pred = self._predict(frame_index) if self.active else None
        if pred is None or self.missing > 3:
            return best
        gate = self.cfg.base_gate_px + self.cfg.velocity_gate_factor * self._speed()
        gate *= 1.0 + 0.6 * self.missing
        if float(np.hypot(best.x - pred[0], best.y - pred[1])) <= gate:
            return best
        # 1순위가 물리적으로 불가능한 점프면, 게이트 안의 차순위를 본다
        inside = [d for d in allowed
                  if float(np.hypot(d.x - pred[0], d.y - pred[1])) <= gate]
        if inside:
            return max(inside, key=lambda d: d.confidence)
        return best if self.missing >= 2 else None

    # 오프라인 -------------------------------------------------------------
    def run(self, frames: Iterable[np.ndarray], fps: float = 30.0, total: Optional[int] = None) -> BallTrack:
        self.reset()
        n = 0
        for i, frame in enumerate(frames):
            self.update(frame, i)
            n = i + 1
        return self.to_track(total if total is not None else n, fps)


# --- 후처리 ----------------------------------------------------------------
def interpolate_track(track: BallTrack, max_gap: int = 8) -> BallTrack:
    """짧은 결측 구간을 선형 보간으로 메운다(긴 구간은 남겨둔다)."""
    pos = list(track.positions)
    conf = list(track.confidence) or [0.0] * len(pos)
    i = 0
    n = len(pos)
    while i < n:
        if pos[i] is not None:
            i += 1
            continue
        j = i
        while j < n and pos[j] is None:
            j += 1
        gap = j - i
        if 0 < i and j < n and gap <= max_gap:
            (x0, y0), (x1, y1) = pos[i - 1], pos[j]
            for k in range(gap):
                t = (k + 1) / (gap + 1)
                pos[i + k] = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
                conf[i + k] = 0.3
        i = j
    return BallTrack(positions=pos, confidence=conf, fps=track.fps)


def smooth_track(track: BallTrack, window: int = 5, poly: int = 2) -> BallTrack:
    """궤적 스무딩. 바운스의 급격한 꺾임을 뭉개지 않도록 짧은 윈도우를 쓴다."""
    pos = list(track.positions)
    n = len(pos)
    out: list[Optional[tuple[float, float]]] = list(pos)
    half = window // 2
    for i in range(n):
        if pos[i] is None:
            continue
        xs, ys, ts = [], [], []
        for k in range(max(0, i - half), min(n, i + half + 1)):
            if pos[k] is not None:
                xs.append(pos[k][0])
                ys.append(pos[k][1])
                ts.append(k - i)
        if len(xs) < poly + 1:
            continue
        cx = np.polyfit(ts, xs, min(poly, len(xs) - 1))
        cy = np.polyfit(ts, ys, min(poly, len(ys) - 1))
        out[i] = (float(np.polyval(cx, 0)), float(np.polyval(cy, 0)))
    return BallTrack(positions=out, confidence=list(track.confidence), fps=track.fps)


def track_ball(
    frames: Iterable[np.ndarray], fps: float = 30.0, total: Optional[int] = None, **tracker_kw
) -> BallTrack:
    """편의 함수: 검출 -> 추적 -> 보간 -> 스무딩."""
    tracker = BallTracker(**tracker_kw)
    raw = tracker.run(frames, fps=fps, total=total)
    return smooth_track(interpolate_track(raw))


def iter_video(path: str, stride: int = 1) -> Iterator[np.ndarray]:
    cap = cv2.VideoCapture(path)
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % stride == 0:
                yield frame
            i += 1
    finally:
        cap.release()


def video_meta(path: str) -> tuple[float, int, tuple[int, int]]:
    cap = cv2.VideoCapture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return float(fps), n, (w, h)
    finally:
        cap.release()


__all__ = [
    "MotionBallDetector",
    "BallTracker",
    "track_ball",
    "interpolate_track",
    "smooth_track",
    "iter_video",
    "video_meta",
]
