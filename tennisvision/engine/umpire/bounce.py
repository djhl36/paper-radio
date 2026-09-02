"""공 궤적에서 이벤트(바운스 / 라켓 타격 / 네트)를 뽑아낸다.

핵심 아이디어 — **지면 투영 좌표에서 본다**

공중의 공을 지면 호모그래피로 투영하면 실제보다 카메라에서 먼 쪽으로 밀린
"겉보기 지면 위치" G(t) 가 된다. 카메라 바로 아래 지점을 N 이라 할 때
공의 실제 지면 위치 P 와는

    G = N + k·(P − N),   k = h_cam / (h_cam − h_ball) ≥ 1

관계다(카메라·공·G 가 한 직선 위에 있으니까). 여기서 두 가지가 따라온다.

1. 바운스에서는 h_ball = 0 이라 k = 1, 즉 **G = P**. 그래서 인/아웃 판정은
   오직 바운스 시점에서만 정확하고, 우리도 거기서만 판정한다.
2. G 의 속도가 불연속으로 꺾이는 지점이 곧 이벤트다. 그런데 그 꺾임의 크기가
   두 이벤트를 구분해 준다.
     - 바운스: 수직 속도만 뒤집힌다 → ΔG 는 N 방향(반경)으로만, 크기 ≈ 2·|v_z|
     - 라켓 타격: 공이 통째로 되돌아온다 → 크기 ≈ 2·|v| 로 훨씬 크고,
       접선(옆) 방향 성분이 함께 생긴다
   그래서 |ΔG| 를 공의 속도로 나눈 값 하나로 둘이 갈린다(실측 분리도 양호).

이미지 픽셀이 아니라 지면 m/s 단위로 재기 때문에 코트 안쪽/바깥쪽, 해상도,
fps 가 달라져도 같은 임계값이 통한다.

정밀도
    검출된 프레임을 그대로 바운스 지점으로 쓰면 30fps 에서 1~2m 씩 틀린다.
    그래서 앞뒤 궤적에 2차 곡선을 각각 맞추고 **두 곡선의 교점**으로 서브프레임
    위치를 복원한다. 이벤트 프레임에 공이 안 잡혀도 앞뒤만 있으면 복원된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..geometry import image_to_court
from ..schema import BallEvent, BallTrack, Calibration, PlayerTrack, Side


@dataclass
class EventConfig:
    window: int = 5                  # 좌/우 곡선 적합 창 크기(프레임)
    min_points: int = 3              # 각 창에 최소 이만큼은 있어야 한다
    min_break_ms: float = 6.0        # 속도 불연속 하한 (m/s)
    break_ratio: float = 0.55        # 공 속도 대비 비율 임계
    hit_ratio: float = 1.50          # |Δv|/속도 가 이보다 크면 라켓 타격
    hit_tangential_ratio: float = 0.35   # 접선 성분이 크면 타격 쪽으로 기운다
    min_separation: int = 5          # 이벤트 간 최소 간격(프레임)
    player_radius_m: float = 2.5     # 타격 주체 판정 반경
    net_band_m: float = 0.9          # 네트 판정 밴드
    net_speed_drop: float = 0.5      # 네트 판정: 속도가 이 비율 이하로 급감
    max_ground_speed: float = 75.0   # m/s. 이보다 빠른 겉보기 속도는 노이즈로 본다


# --- 겉보기 지면 궤적 -------------------------------------------------------
class GroundTrack:
    """이미지 궤적을 지면 좌표(m)로 투영해 둔 것."""

    def __init__(self, track: Optional[BallTrack] = None, calib: Optional[Calibration] = None,
                 fps: float = 30.0):
        self.calib = calib
        self.pts: list[Optional[np.ndarray]] = []
        self.image_pts: list[Optional[tuple[float, float]]] = []
        self.fps = (track.fps if track else fps) or fps
        if track is not None and calib is not None:
            for i in range(len(track)):
                self.append(track.at(i))

    @property
    def n(self) -> int:
        return len(self.pts)

    def append(self, image_xy: Optional[tuple[float, float]]) -> None:
        """확정된 프레임 하나를 뒤에 붙인다(실시간 세션용)."""
        self.image_pts.append(image_xy)
        if image_xy is None or self.calib is None:
            self.pts.append(None)
            return
        x, y = image_to_court(self.calib.H, image_xy[0], image_xy[1])
        self.pts.append(np.array([x, y], dtype=np.float64))

    def at(self, i: int) -> Optional[np.ndarray]:
        if 0 <= i < self.n:
            return self.pts[i]
        return None

    def _collect(self, rng) -> tuple[np.ndarray, np.ndarray]:
        idx, pts = [], []
        for k in rng:
            p = self.at(k)
            if p is not None:
                idx.append(k)
                pts.append(p)
        return np.asarray(idx, dtype=float), (np.asarray(pts) if pts else np.zeros((0, 2)))

    def fit(self, rng, deg: int = 2) -> Optional[tuple[np.ndarray, np.ndarray, float]]:
        """구간에 다항식을 맞춘다. (cx, cy, n_points) — 프레임 인덱스 기준."""
        idx, pts = self._collect(rng)
        if len(idx) < 2:
            return None
        d = min(deg, len(idx) - 1)
        cx = np.polyfit(idx, pts[:, 0], d)
        cy = np.polyfit(idx, pts[:, 1], d)
        return cx, cy, float(len(idx))

    def velocity(self, rng, at: float) -> Optional[np.ndarray]:
        """구간 적합의 at 프레임에서의 속도 (m/s)."""
        f = self.fit(rng)
        if f is None:
            return None
        cx, cy, n = f
        if n < 2:
            return None
        vx = float(np.polyval(np.polyder(cx), at)) * self.fps
        vy = float(np.polyval(np.polyder(cy), at)) * self.fps
        return np.array([vx, vy])

    def speed(self, rng) -> float:
        idx, pts = self._collect(rng)
        if len(idx) < 2:
            return 0.0
        steps = np.linalg.norm(np.diff(pts, axis=0), axis=1) / np.maximum(np.diff(idx), 1)
        return float(np.median(steps) * self.fps)

    def count(self, rng) -> int:
        return int(sum(1 for k in rng if self.at(k) is not None))


@dataclass
class BreakProfile:
    magnitude: np.ndarray      # |Δv| (m/s)
    radial: np.ndarray         # 카메라 나디르 반경 방향 성분
    tangential: np.ndarray     # 접선 방향 성분
    speed: np.ndarray          # 국소 공 속도 (m/s)
    valid: np.ndarray          # 좌/우 창이 모두 찬 프레임


def _nadir(calib: Calibration) -> Optional[np.ndarray]:
    """카메라 바로 아래 지점(코트 좌표). 카메라 추정이 되면 정확히, 아니면 근사."""
    try:
        from ..vision.camera import estimate_camera

        cam = estimate_camera(calib)
        if cam is not None:
            return np.asarray(cam.nadir, dtype=float)
    except Exception:
        pass
    return None


def break_profile(gt: GroundTrack, calib: Calibration, cfg: EventConfig | None = None) -> BreakProfile:
    cfg = cfg or EventConfig()
    W = cfg.window
    n = gt.n
    mag = np.zeros(n)
    rad = np.zeros(n)
    tan = np.zeros(n)
    spd = np.zeros(n)
    valid = np.zeros(n, dtype=bool)
    nadir = _nadir(calib)

    for i in range(n):
        left_rng = range(i - W, i)
        right_rng = range(i + 1, i + W + 1)
        if gt.count(left_rng) < cfg.min_points or gt.count(right_rng) < cfg.min_points:
            continue
        vl = gt.velocity(left_rng, i)
        vr = gt.velocity(right_rng, i)
        if vl is None or vr is None:
            continue
        s = 0.5 * (float(np.linalg.norm(vl)) + float(np.linalg.norm(vr)))
        if s > cfg.max_ground_speed:
            continue
        dv = vr - vl
        valid[i] = True
        mag[i] = float(np.linalg.norm(dv))
        spd[i] = s
        pos = gt.at(i)
        if pos is None:
            f = gt.fit(range(i - W, i + W + 1))
            pos = np.array([np.polyval(f[0], i), np.polyval(f[1], i)]) if f else None
        if pos is not None and nadir is not None:
            r = pos - nadir
            nr = float(np.linalg.norm(r))
            if nr > 1e-6:
                u = r / nr
                t = np.array([-u[1], u[0]])
                rad[i] = abs(float(dv @ u))
                tan[i] = abs(float(dv @ t))
        else:
            rad[i] = mag[i]
    return BreakProfile(mag, rad, tan, spd, valid)


# --- 서브프레임 보정 --------------------------------------------------------
def refine_event(gt: GroundTrack, i: int, cfg: EventConfig) -> Optional[tuple[float, np.ndarray]]:
    """앞뒤 궤적의 교점으로 이벤트 시각과 지면 위치를 복원한다."""
    W = cfg.window
    left = gt.fit(range(i - W, i))
    right = gt.fit(range(i + 1, i + W + 1))
    if left is None or right is None:
        return None
    lx, ly, _ = left
    rx, ry, _ = right
    ts = np.linspace(i - W * 0.5, i + W * 0.5, 61)
    dx = np.polyval(lx, ts) - np.polyval(rx, ts)
    dy = np.polyval(ly, ts) - np.polyval(ry, ts)
    d = np.hypot(dx, dy)
    j = int(np.argmin(d))
    t = float(ts[j])
    pos = np.array([
        0.5 * (float(np.polyval(lx, t)) + float(np.polyval(rx, t))),
        0.5 * (float(np.polyval(ly, t)) + float(np.polyval(ry, t))),
    ])
    return t, pos


# --- 이벤트 검출 ------------------------------------------------------------
def detect_events(
    track: BallTrack,
    calib: Calibration,
    players: Optional[dict[Side, PlayerTrack]] = None,
    cfg: EventConfig | None = None,
) -> list[BallEvent]:
    cfg = cfg or EventConfig()
    gt = GroundTrack(track, calib)
    prof = break_profile(gt, calib, cfg)

    base_speed = float(np.median(prof.speed[prof.valid])) if prof.valid.any() else 0.0
    threshold = max(cfg.min_break_ms, cfg.break_ratio * base_speed)

    order = np.argsort(-prof.magnitude)
    chosen: list[int] = []
    for i in order:
        if not prof.valid[i] or prof.magnitude[i] < threshold:
            break
        if any(abs(int(i) - c) < cfg.min_separation for c in chosen):
            continue
        chosen.append(int(i))
    chosen.sort()

    events: list[BallEvent] = []
    for i in chosen:
        pos_at = {side: pt.court_at(i) for side, pt in (players or {}).items()}
        ev = classify_event(
            gt, calib, i,
            magnitude=float(prof.magnitude[i]), speed=float(prof.speed[i]),
            radial=float(prof.radial[i]), tangential=float(prof.tangential[i]),
            player_positions=pos_at, cfg=cfg,
        )
        if ev is not None:
            events.append(ev)
    events.sort(key=lambda e: e.t)
    annotate_speeds(events)
    return events




# --- 이벤트 분류 (오프라인/실시간 공용) --------------------------------------
def classify_event(
    gt: GroundTrack,
    calib: Calibration,
    i: int,
    magnitude: float,
    speed: float,
    radial: float,
    tangential: float,
    player_positions: Optional[dict] = None,
    cfg: EventConfig | None = None,
) -> Optional[BallEvent]:
    """프레임 i 의 속도 불연속을 하나의 이벤트로 확정한다.

    player_positions 는 {side: (court_x, court_y) | None}.
    """
    cfg = cfg or EventConfig()
    refined = refine_event(gt, i, cfg)
    if refined is not None:
        t_frame, pos = refined
    else:
        p = gt.at(i)
        if p is None:
            return None
        t_frame, pos = float(i), p

    ratio = magnitude / max(speed, 1e-6)
    tan_ratio = tangential / max(radial, 1e-6)
    is_hit = ratio >= cfg.hit_ratio or tan_ratio >= cfg.hit_tangential_ratio

    kind = "hit" if is_hit else "bounce"
    if not is_hit and abs(pos[1]) <= cfg.net_band_m:
        vl = gt.velocity(range(i - cfg.window, i), i)
        vr = gt.velocity(range(i + 1, i + cfg.window + 1), i)
        if vl is not None and vr is not None:
            if float(np.linalg.norm(vr)) < cfg.net_speed_drop * float(np.linalg.norm(vl)):
                kind = "net"

    by_side: Optional[Side] = None
    if kind == "hit":
        by_side = "near" if pos[1] < 0 else "far"
        if player_positions:
            best = None
            for side, cp in player_positions.items():
                if cp is None:
                    continue
                d = float(np.hypot(pos[0] - cp[0], pos[1] - cp[1]))
                if best is None or d < best[0]:
                    best = (d, side)
            if best and best[0] <= cfg.player_radius_m:
                by_side = best[1]  # type: ignore[assignment]

    margin = abs(ratio - cfg.hit_ratio) / cfg.hit_ratio
    conf = float(np.clip(0.35 + 0.5 * min(margin, 1.0) + 0.15 * min(magnitude / 40.0, 1.0), 0.1, 1.0))

    return BallEvent(
        kind=kind,  # type: ignore[arg-type]
        frame=int(round(t_frame)),
        t=round(t_frame / gt.fps, 4),
        image_xy=_to_image(calib, pos),
        court_xy=(round(float(pos[0]), 3), round(float(pos[1]), 3)),
        confidence=round(conf, 3),
        by_side=by_side,
    )


def _to_image(calib: Calibration, court_xy) -> tuple[float, float]:
    from ..geometry import court_to_image

    try:
        return court_to_image(calib.H, float(court_xy[0]), float(court_xy[1]))
    except Exception:
        return (0.0, 0.0)


def annotate_speeds(events: list[BallEvent]) -> None:
    """타격 -> 다음 바운스 구간의 평균 지면 속도(km/h).

    지면 투영 기준이라 3D 실제 구속보다 낮게 나온다. 리포트에도 그렇게 적는다.
    """
    for a, b in zip(events, events[1:]):
        if a.kind != "hit" or b.kind not in ("bounce", "net"):
            continue
        if a.court_xy is None or b.court_xy is None:
            continue
        dt = b.t - a.t
        if dt <= 1e-3:
            continue
        dist = float(np.hypot(b.court_xy[0] - a.court_xy[0], b.court_xy[1] - a.court_xy[1]))
        a.speed_kmh = round(dist / dt * 3.6, 1)


# --- 실시간용 단일 프레임 API ----------------------------------------------
def break_at(gt: GroundTrack, i: int, nadir: Optional[np.ndarray] = None,
             cfg: EventConfig | None = None) -> tuple[float, float, float, float]:
    """프레임 i 의 (|Δv|, 속도, 반경 성분, 접선 성분). 창이 안 차면 전부 0."""
    cfg = cfg or EventConfig()
    W = cfg.window
    if gt.count(range(i - W, i)) < cfg.min_points or gt.count(range(i + 1, i + W + 1)) < cfg.min_points:
        return 0.0, 0.0, 0.0, 0.0
    vl = gt.velocity(range(i - W, i), i)
    vr = gt.velocity(range(i + 1, i + W + 1), i)
    if vl is None or vr is None:
        return 0.0, 0.0, 0.0, 0.0
    s = 0.5 * (float(np.linalg.norm(vl)) + float(np.linalg.norm(vr)))
    if s > cfg.max_ground_speed:
        return 0.0, 0.0, 0.0, 0.0
    dv = vr - vl
    mag = float(np.linalg.norm(dv))
    rad, tan = mag, 0.0
    pos = gt.at(i)
    if pos is not None and nadir is not None:
        r = pos - nadir
        nr = float(np.linalg.norm(r))
        if nr > 1e-6:
            u = r / nr
            t = np.array([-u[1], u[0]])
            rad = abs(float(dv @ u))
            tan = abs(float(dv @ t))
    return mag, s, rad, tan


def camera_nadir(calib: Calibration) -> Optional[np.ndarray]:
    return _nadir(calib)


# --- 판정 오차 예산 ---------------------------------------------------------
def bounce_uncertainty_cm(
    track: BallTrack, calib: Calibration, frame: int, image_xy: tuple[float, float]
) -> float:
    """이 바운스 판정의 1시그마 오차 예산(cm).

      1) 캘리브레이션 재투영 오차
      2) 서브프레임 보정 후 남는 타이밍 오차 (프레임 간 이동량의 1/4)
      3) 공 검출 중심의 픽셀 오차 (약 2px)
    """
    from ..geometry import meters_per_pixel

    mpp = meters_per_pixel(calib.H, image_xy[0], image_xy[1])
    calib_err = calib.reprojection_error_m

    prev, nxt = track.at(frame - 1), track.at(frame + 1)
    step_px = 0.0
    if prev is not None and nxt is not None:
        step_px = float(np.hypot(nxt[0] - prev[0], nxt[1] - prev[1]) / 2)
    elif prev is not None:
        step_px = float(np.hypot(image_xy[0] - prev[0], image_xy[1] - prev[1]))
    timing_err = 0.25 * step_px * mpp
    detect_err = 2.0 * mpp
    sigma = float(np.sqrt(calib_err ** 2 + timing_err ** 2 + detect_err ** 2))
    return sigma * 100.0


__all__ = [
    "EventConfig", "GroundTrack", "BreakProfile",
    "break_profile", "break_at", "camera_nadir",
    "detect_events", "classify_event", "refine_event",
    "annotate_speeds", "bounce_uncertainty_cm",
]
