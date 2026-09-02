"""단안 카메라에서 공의 3D 궤적을 복원하고, 거기서 이벤트를 뽑는다.

원리
    카메라를 알면 이미지의 공 하나는 3D 광선 하나를 준다. 광선만으로는 깊이를
    모르지만, 이벤트와 이벤트 사이에서 공은 **중력만 받는 포물선**이라는 강한
    물리 제약이 있다.

        P(t) = P0 + V·t + (0, 0, -g/2)·t^2

    미지수는 P0, V 여섯 개뿐이고, 관측 한 프레임마다 "P(t)가 그 광선 위에 있다"
    는 선형 제약 2개가 생긴다. 그래서 한 구간에 3프레임 이상만 잡히면 최소자승
    으로 3D 궤적이 딱 떨어진다.

    구간(arc)을 이어 붙이다가 재투영 오차가 튀는 지점이 곧 이벤트(바운스/타격/
    네트)다. 이벤트 시각과 위치는 앞뒤 두 포물선의 교점으로 구하므로,
    **바운스 순간에 공이 검출되지 않아도** 위치를 복원할 수 있다.

이 방식의 이점
    - 인/아웃: 바운스 지점을 서브프레임 정밀도로 얻는다 (프레임 샘플링 오차 소거)
    - 구속: 지면 투영이 아니라 진짜 3D 속도
    - 네트 클리어런스 / 바운스 높이 / 궤적 각도 -> 스핀·구질 분석의 기초
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from ..geometry import BALL_RADIUS, NET_HEIGHT_CENTER
from ..schema import BallEvent, BallTrack, Side
from ..vision.camera import CameraModel

G = 9.81
GRAV = np.array([0.0, 0.0, -G])


def _skew(d: np.ndarray) -> np.ndarray:
    return np.array([[0, -d[2], d[1]], [d[2], 0, -d[0]], [-d[1], d[0], 0]])


@dataclass
class Arc:
    """이벤트 사이의 자유 비행 구간."""

    start: int
    end: int
    t0: float                 # 기준 시각(초) = start / fps
    P0: np.ndarray            # t0 에서의 위치 (m)
    V: np.ndarray             # t0 에서의 속도 (m/s)
    residual_px: float
    n_points: int
    fps: float

    def at(self, t: float) -> np.ndarray:
        """절대 시각 t(초)의 3D 위치."""
        dt = t - self.t0
        return self.P0 + self.V * dt + 0.5 * GRAV * dt * dt

    def velocity(self, t: float) -> np.ndarray:
        return self.V + GRAV * (t - self.t0)

    def speed_kmh(self, t: Optional[float] = None) -> float:
        v = self.V if t is None else self.velocity(t)
        return float(np.linalg.norm(v) * 3.6)

    @property
    def t_start(self) -> float:
        return self.start / self.fps

    @property
    def t_end(self) -> float:
        return self.end / self.fps

    def ground_crossing(self, t_from: float, t_to: float) -> Optional[float]:
        """z = 공 반지름이 되는 시각 (구간 안에서)."""
        a, b, c = 0.5 * GRAV[2], self.V[2], self.P0[2] - BALL_RADIUS
        # z(dt) = c + b*dt + a*dt^2, dt = t - t0
        roots = np.roots([a, b, c]) if abs(a) > 1e-12 else ([-c / b] if abs(b) > 1e-12 else [])
        best = None
        for r in roots:
            if abs(np.imag(r)) > 1e-6:
                continue
            t = self.t0 + float(np.real(r))
            if t_from - 1e-6 <= t <= t_to + 1e-6:
                if best is None or t < best:
                    best = t
        return best

    def net_crossing(self) -> Optional[tuple[float, float, float]]:
        """네트 평면(y=0)을 지나는 시각과 그때의 (x, z)."""
        if abs(self.V[1]) < 1e-6:
            return None
        dt = -self.P0[1] / self.V[1]
        t = self.t0 + dt
        if not (self.t_start - 0.3 <= t <= self.t_end + 0.3):
            return None
        p = self.at(t)
        return t, float(p[0]), float(p[2])


# --- 구간 적합 -------------------------------------------------------------
def fit_arc(
    camera: CameraModel, track: BallTrack, frames: Sequence[int], fps: float
) -> Optional[Arc]:
    """주어진 프레임들의 관측으로 하나의 포물선을 최소자승 적합."""
    obs = [(f, track.at(f)) for f in frames]
    obs = [(f, p) for f, p in obs if p is not None]
    if len(obs) < 3:
        return None
    ref = obs[0][0]
    t0 = ref / fps
    C = camera.position

    rows = []
    rhs = []
    pts = np.asarray([p for _, p in obs], dtype=np.float64)
    dirs = camera.rays(pts)
    for (f, _), d in zip(obs, dirs):
        dt = (f - ref) / fps
        M = _skew(d)
        rows.append(np.hstack([M, dt * M]))
        rhs.append(M @ (C - 0.5 * GRAV * dt * dt))
    A = np.vstack(rows)
    b = np.concatenate(rhs)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    P0, V = sol[:3], sol[3:]
    if not np.isfinite(sol).all():
        return None

    arc = Arc(start=obs[0][0], end=obs[-1][0], t0=t0, P0=P0, V=V,
              residual_px=0.0, n_points=len(obs), fps=fps)
    arc.residual_px = _reprojection_error(camera, arc, obs, fps)
    return arc


def _reprojection_error(camera: CameraModel, arc: Arc, obs, fps: float) -> float:
    world = np.asarray([arc.at(f / fps) for f, _ in obs])
    if (world[:, 2] < -1.5).any():           # 지면 아래로 내려가는 해는 폐기
        return 1e6
    proj = camera.project(world)
    meas = np.asarray([p for _, p in obs], dtype=np.float64)
    return float(np.sqrt(np.mean(np.sum((proj - meas) ** 2, axis=1))))


@dataclass
class SegmentConfig:
    max_residual_px: float = 3.5      # 이 값을 넘으면 구간이 끊긴 것으로 본다
    min_points: int = 4
    max_gap: int = 8                  # 검출 공백이 이보다 길면 무조건 구간을 끊는다
    max_arc_frames: int = 120
    min_speed_kmh: float = 8.0        # 사실상 정지한 구간(공 줍기 등)은 버린다


def segment_arcs(
    camera: CameraModel, track: BallTrack, fps: float, cfg: SegmentConfig | None = None
) -> list[Arc]:
    """궤적 전체를 자유 비행 구간들로 쪼갠다."""
    cfg = cfg or SegmentConfig()
    valid = [i for i in range(len(track)) if track.at(i) is not None]
    arcs: list[Arc] = []
    i = 0
    while i < len(valid):
        window: list[int] = []
        best: Optional[Arc] = None
        j = i
        while j < len(valid):
            f = valid[j]
            if window and (f - window[-1] > cfg.max_gap or f - window[0] > cfg.max_arc_frames):
                break
            window.append(f)
            if len(window) < cfg.min_points:
                j += 1
                continue
            arc = fit_arc(camera, track, window, fps)
            if arc is None or arc.residual_px > cfg.max_residual_px:
                window.pop()
                break
            best = arc
            j += 1
        if best is not None and best.speed_kmh() >= cfg.min_speed_kmh:
            arcs.append(best)
            i = valid.index(best.end) + 1 if best.end in valid else j
        else:
            i += 1
    return arcs


# --- 구간 경계 -> 이벤트 ---------------------------------------------------
@dataclass
class EventFromArc:
    kind: str
    t: float
    frame: int
    world: np.ndarray
    speed_in_kmh: Optional[float]
    speed_out_kmh: Optional[float]
    height_m: float
    confidence: float
    arc_before: Optional[Arc] = None
    arc_after: Optional[Arc] = None


def _junction_time(a: Arc, b: Arc, fps: float) -> float:
    """두 포물선이 가장 가까워지는 시각(= 접촉 순간) 을 미세 탐색으로 찾는다."""
    lo = a.t_end - 6.0 / fps
    hi = b.t_start + 6.0 / fps
    if hi <= lo:
        return 0.5 * (a.t_end + b.t_start)
    ts = np.linspace(lo, hi, 80)
    d = np.array([np.linalg.norm(a.at(t) - b.at(t)) for t in ts])
    return float(ts[int(np.argmin(d))])


def events_from_arcs(
    arcs: Sequence[Arc],
    fps: float,
    bounce_height_m: float = 0.28,
    hit_height_range: tuple[float, float] = (0.15, 3.4),
    net_band_m: float = 0.6,
) -> list[EventFromArc]:
    """구간 경계(그리고 구간 내부의 지면 접촉)를 이벤트로 변환."""
    out: list[EventFromArc] = []

    for k, (a, b) in enumerate(zip(arcs, arcs[1:])):
        t = _junction_time(a, b, fps)
        pa, pb = a.at(t), b.at(t)
        world = 0.5 * (pa + pb)
        gap_m = float(np.linalg.norm(pa - pb))
        h = float(world[2])
        v_in = a.speed_kmh(t)
        v_out = b.speed_kmh(t)

        if h <= bounce_height_m:
            kind = "bounce"
        elif abs(world[1]) <= net_band_m and h <= NET_HEIGHT_CENTER + 0.25 and v_out < v_in * 0.75:
            kind = "net"
        elif hit_height_range[0] <= h <= hit_height_range[1]:
            kind = "hit"
        else:
            kind = "bounce" if h < 1.0 else "hit"

        conf = float(np.clip(1.0 - gap_m / 1.5, 0.15, 1.0))
        conf *= float(np.clip(1.0 - (a.residual_px + b.residual_px) / 12.0, 0.2, 1.0))
        out.append(
            EventFromArc(kind=kind, t=t, frame=int(round(t * fps)), world=world,
                         speed_in_kmh=round(v_in, 1), speed_out_kmh=round(v_out, 1),
                         height_m=round(h, 3), confidence=round(conf, 3),
                         arc_before=a, arc_after=b)
        )

    # 구간 내부에서 지면을 뚫고 지나가면(= 세그멘테이션이 놓친 바운스) 보완
    for a in arcs:
        t = a.ground_crossing(a.t_start + 1.0 / fps, a.t_end - 1.0 / fps)
        if t is None:
            continue
        if any(abs(e.t - t) < 4.0 / fps for e in out):
            continue
        world = a.at(t)
        out.append(
            EventFromArc(kind="bounce", t=t, frame=int(round(t * fps)), world=world,
                         speed_in_kmh=round(a.speed_kmh(t), 1),
                         speed_out_kmh=round(a.speed_kmh(t), 1),
                         height_m=float(world[2]), confidence=0.5,
                         arc_before=a, arc_after=a)
        )

    out.sort(key=lambda e: e.t)
    return out


def to_ball_events(
    raw: Sequence[EventFromArc],
    camera: CameraModel,
    player_positions_at=None,
    player_radius_m: float = 2.5,
) -> list[BallEvent]:
    """엔진 공통 스키마(BallEvent)로 변환하고 타격 주체를 붙인다."""
    events: list[BallEvent] = []
    for e in raw:
        img = camera.project([e.world])[0]
        by_side: Optional[Side] = None
        if e.kind == "hit":
            court_xy = (float(e.world[0]), float(e.world[1]))
            by_side = "near" if court_xy[1] < 0 else "far"
            if player_positions_at is not None:
                pos = player_positions_at(e.frame) or {}
                best = None
                for side, p in pos.items():
                    if p is None:
                        continue
                    d = float(np.hypot(court_xy[0] - p[0], court_xy[1] - p[1]))
                    if best is None or d < best[0]:
                        best = (d, side)
                if best and best[0] <= player_radius_m:
                    by_side = best[1]  # type: ignore[assignment]
        events.append(
            BallEvent(
                kind=e.kind,  # type: ignore[arg-type]
                frame=e.frame,
                t=round(e.t, 4),
                image_xy=(float(img[0]), float(img[1])),
                court_xy=(round(float(e.world[0]), 3), round(float(e.world[1]), 3)),
                confidence=e.confidence,
                by_side=by_side,
                speed_kmh=e.speed_out_kmh if e.kind == "hit" else e.speed_in_kmh,
            )
        )
    return events


def bounce_uncertainty_cm_3d(event: EventFromArc, camera: CameraModel,
                             calib_error_m: float) -> float:
    """3D 복원 기반 바운스 판정의 1시그마 오차 예산(cm).

    구성: 캘리브레이션 오차 + 두 포물선 교점의 불일치(gap) + 적합 잔차를
    코트 스케일로 환산한 값.
    """
    gap = 0.0
    if event.arc_before is not None and event.arc_after is not None and event.arc_before is not event.arc_after:
        gap = float(np.linalg.norm(event.arc_before.at(event.t) - event.arc_after.at(event.t)))
    resid_px = np.mean([
        a.residual_px for a in (event.arc_before, event.arc_after) if a is not None
    ]) if (event.arc_before or event.arc_after) else 2.0
    # 픽셀 잔차 -> 미터: 바운스 지점에서 1px 이 코트에서 몇 m 인지
    u, v = camera.project([event.world])[0]
    p0 = np.asarray(camera.ground_point(u, v))
    p1 = np.asarray(camera.ground_point(u + 1.0, v))
    p2 = np.asarray(camera.ground_point(u, v + 1.0))
    mpp = 0.5 * (np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p0))
    sigma = float(np.sqrt(calib_error_m ** 2 + (0.5 * gap) ** 2 + (resid_px * mpp) ** 2))
    return max(sigma * 100.0, 0.5)


__all__ = [
    "Arc", "SegmentConfig", "EventFromArc",
    "fit_arc", "segment_arcs", "events_from_arcs", "to_ball_events",
    "bounce_uncertainty_cm_3d",
]
