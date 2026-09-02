"""합성 테니스 경기 영상 생성기.

실제 경기 영상 없이도 파이프라인 전체(추적 -> 이벤트 -> 판정 -> 점수 ->
리포트 -> 하이라이트)를 끝까지 돌려 보고 정답과 비교하기 위한 도구다.
공은 3D 포물선 + 반발 계수로 움직이고, 카메라는 베이스라인 뒤 높은 곳에 둔
핀홀 모델로 투영한다. 정답(각 바운스의 코트 좌표, 포인트 승자)을 함께
저장하므로 판정 정확도를 수치로 검증할 수 있다.

    python tools/simulate.py --out data/sample_match.mp4 --points 8
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.geometry import (  # noqa: E402
    DOUBLES_HALF_W,
    HALF_LENGTH,
    LINE_SEGMENTS,
    SERVICE_LINE_Y,
    SINGLES_HALF_W,
    serve_target_box,
)

G = 9.81
RESTITUTION = 0.72
FRICTION = 0.78


# --- 카메라 ---------------------------------------------------------------
@dataclass
class Camera:
    width: int = 1280
    height: int = 720
    f: float = 800.0
    eye: tuple = (0.4, -20.0, 7.0)
    look_at: tuple = (0.0, 1.0, 0.0)

    def __post_init__(self):
        eye = np.asarray(self.eye, float)
        target = np.asarray(self.look_at, float)
        fwd = target - eye
        fwd /= np.linalg.norm(fwd)
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        # 카메라 좌표계: x=right, y=-up(이미지 y는 아래로), z=forward
        self.R = np.stack([right, -up, fwd], axis=0)
        self.t = -self.R @ eye
        self.K = np.array([[self.f, 0, self.width / 2], [0, self.f, self.height / 2], [0, 0, 1]], float)

    def project(self, p: np.ndarray) -> tuple[float, float, float]:
        p = np.asarray(p, float)
        c = self.R @ p + self.t
        z = max(c[2], 0.05)
        u = self.f * c[0] / z + self.width / 2
        v = self.f * c[1] / z + self.height / 2
        # 카메라 뒤/극단 좌표에서 int 변환이 터지지 않도록 넉넉히 자른다
        lim = 10 * max(self.width, self.height)
        return float(np.clip(u, -lim, lim)), float(np.clip(v, -lim, lim)), float(z)

    def project_many(self, pts) -> list[tuple[float, float, float]]:
        return [self.project(p) for p in pts]


# --- 공 물리 --------------------------------------------------------------
def launch_velocity(p0, p1, flight_s: float) -> np.ndarray:
    """p0 에서 출발해 flight_s 뒤 p1 에 도달하는 초기 속도 (중력 보정)."""
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    v = (p1 - p0) / flight_s
    v[2] = (p1[2] - p0[2]) / flight_s + 0.5 * G * flight_s
    return v


def step(p: np.ndarray, v: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray, bool]:
    """한 스텝 진행. 지면에 닿으면 튕기고 True 를 돌려준다."""
    v = v.copy()
    v[2] -= G * dt
    p = p + v * dt
    bounced = False
    if p[2] <= 0.0335:
        p[2] = 0.0335
        v[2] = -v[2] * RESTITUTION
        v[0] *= FRICTION
        v[1] *= FRICTION
        bounced = True
    return p, v, bounced


# --- 랠리 스크립트 --------------------------------------------------------
@dataclass
class SimPoint:
    server: str                  # "near" | "far"
    court: str                   # "deuce" | "ad"
    shots: list = field(default_factory=list)   # (target_xy, flight_s) 목록
    outcome: str = "winner"      # winner | out | net | double_fault


def default_script(n_points: int, seed: int = 7) -> list[SimPoint]:
    rng = np.random.default_rng(seed)
    pts: list[SimPoint] = []
    for i in range(n_points):
        server = "near" if (i // 2) % 2 == 0 else "far"
        court = "deuce" if i % 2 == 0 else "ad"
        box = serve_target_box(server, court)  # type: ignore[arg-type]
        # 서브 착지점: 박스 안쪽 깊게
        sx = float(rng.uniform(min(box.x_min, box.x_max) + 0.4, max(box.x_min, box.x_max) - 0.4))
        sy = float(np.sign(box.y_max + box.y_min) * rng.uniform(SERVICE_LINE_Y * 0.55, SERVICE_LINE_Y * 0.92))
        shots = [((sx, sy), 0.62)]
        rally = int(rng.integers(2, 7))
        side = "far" if server == "near" else "near"
        for k in range(rally):
            side = "far" if side == "near" else "near"
            depth_sign = 1.0 if side == "far" else -1.0
            tx = float(rng.uniform(-SINGLES_HALF_W * 0.85, SINGLES_HALF_W * 0.85))
            ty = depth_sign * float(rng.uniform(5.5, 10.6))
            shots.append(((tx, ty), float(rng.uniform(0.78, 1.02))))
        outcome = ["winner", "winner", "out", "net"][int(rng.integers(0, 4))]
        if outcome == "out":
            side = "far" if side == "near" else "near"
            depth_sign = 1.0 if side == "far" else -1.0
            over = float(rng.uniform(0.25, 0.9))
            shots.append(((float(rng.uniform(-3, 3)), depth_sign * (HALF_LENGTH + over)), 1.0))
        pts.append(SimPoint(server=server, court=court, shots=shots, outcome=outcome))
    return pts


def simulate_point(sp: SimPoint, fps: float, t0: float) -> tuple[list[dict], list[dict], float]:
    """한 포인트의 프레임별 공 위치와 정답 이벤트를 만든다."""
    dt = 1.0 / fps
    frames: list[dict] = []
    truth: list[dict] = []
    server_sign = -1.0 if sp.server == "near" else 1.0
    from engine.geometry import deuce_x_sign

    sign = deuce_x_sign(sp.server) if sp.court == "deuce" else -deuce_x_sign(sp.server)  # type: ignore[arg-type]
    p = np.array([sign * SINGLES_HALF_W * 0.45, server_sign * (HALF_LENGTH + 0.3), 2.55])
    t = t0

    for k, (target_xy, flight) in enumerate(sp.shots):
        target = np.array([target_xy[0], target_xy[1], 0.0335])
        v = launch_velocity(p, target, flight)
        truth.append({"kind": "hit", "t": round(t, 3), "x": round(float(p[0]), 3),
                      "y": round(float(p[1]), 3), "shot": k})
        bounces = 0
        # 다음 샷 직전까지, 또는 (마지막 샷이면) 두 번 튈 때까지 진행
        max_time = flight + (1.35 if k == len(sp.shots) - 1 else 0.30)
        elapsed = 0.0
        while elapsed < max_time:
            p, v, bounced = step(p, v, dt)
            t += dt
            elapsed += dt
            frames.append({"t": round(t, 4), "p": p.copy()})
            if bounced:
                bounces += 1
                truth.append({"kind": "bounce", "t": round(t, 3), "x": round(float(p[0]), 3),
                              "y": round(float(p[1]), 3), "n": bounces})
                if k == len(sp.shots) - 1 and bounces >= 2:
                    break
                if k < len(sp.shots) - 1 and bounces >= 1 and elapsed > flight + 0.20:
                    break
        # 다음 샷은 공이 있는 위치에서 (타점 높이 보정)
        if k < len(sp.shots) - 1:
            p = np.array([p[0], p[1], max(p[2], 0.85)])
    return frames, truth, t


# --- 렌더링 ---------------------------------------------------------------
COURT_COLOR = (104, 78, 44)      # BGR: 하드코트 블루
OUT_COLOR = (86, 104, 60)
LINE_COLOR = (240, 244, 248)
BALL_COLOR = (60, 240, 232)


def draw_court(cam: Camera) -> np.ndarray:
    img = np.full((cam.height, cam.width, 3), OUT_COLOR, np.uint8)
    # 코트 바닥 폴리곤
    pad = 3.5
    ground = [(-DOUBLES_HALF_W - pad, -HALF_LENGTH - pad), (DOUBLES_HALF_W + pad, -HALF_LENGTH - pad),
              (DOUBLES_HALF_W + pad, HALF_LENGTH + pad), (-DOUBLES_HALF_W - pad, HALF_LENGTH + pad)]
    poly = np.array([cam.project((x, y, 0))[:2] for x, y in ground], np.int32)
    cv2.fillPoly(img, [poly], COURT_COLOR)
    for (a, b) in LINE_SEGMENTS:
        p1 = cam.project((a[0], a[1], 0))
        p2 = cam.project((b[0], b[1], 0))
        thick = max(1, int(round(2400.0 / (p1[2] + p2[2]))))
        cv2.line(img, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), LINE_COLOR, thick, cv2.LINE_AA)
    # 네트
    for x in np.linspace(-DOUBLES_HALF_W, DOUBLES_HALF_W, 60):
        top = cam.project((x, 0.0, 0.95 - 0.04 * (1 - abs(x) / DOUBLES_HALF_W)))
        bot = cam.project((x, 0.0, 0.0))
        cv2.line(img, (int(top[0]), int(top[1])), (int(bot[0]), int(bot[1])), (150, 150, 150), 1, cv2.LINE_AA)
    net_l = cam.project((-DOUBLES_HALF_W, 0.0, 1.07))
    net_r = cam.project((DOUBLES_HALF_W, 0.0, 1.07))
    cv2.line(img, (int(net_l[0]), int(net_l[1])), (int(net_r[0]), int(net_r[1])), (245, 245, 245), 2, cv2.LINE_AA)
    return img


def draw_player(img: np.ndarray, cam: Camera, x: float, y: float, color) -> None:
    feet = cam.project((x, y, 0.0))
    head = cam.project((x, y, 1.80))
    half_w = abs(cam.project((x + 0.28, y, 0.9))[0] - cam.project((x - 0.28, y, 0.9))[0]) / 2
    x0, x1 = int(feet[0] - half_w), int(feet[0] + half_w)
    y0, y1 = int(head[1]), int(feet[1])
    cv2.rectangle(img, (x0, y0), (x1, y1), color, -1)
    cv2.circle(img, (int(feet[0]), int(head[1]) - int(half_w * 0.6)), max(2, int(half_w * 0.7)),
               (60, 90, 130), -1)


def render(out_path: str, points: list[SimPoint], fps: float = 30.0, seed: int = 3) -> dict:
    cam = Camera()
    base = draw_court(cam)
    rng = np.random.default_rng(seed)
    # .webm(VP8) 은 브라우저가 바로 재생할 수 있어서 데모 기본값으로 쓴다.
    # OpenCV 휠에는 H.264 인코더가 없어서 .mp4 는 mp4v 로 떨어진다(브라우저 재생 불가).
    fourcc = "VP80" if out_path.lower().endswith(".webm") else "mp4v"
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*fourcc), fps, (cam.width, cam.height))
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter 를 열 수 없습니다 (코덱 {fourcc} 확인)")

    truth_all: list[dict] = []
    point_meta: list[dict] = []
    ball_frames: dict[int, list] = {}     # frame -> [u, v, X, Y, Z]
    t = 0.0
    near_pos = np.array([0.0, -HALF_LENGTH - 0.4])
    far_pos = np.array([0.0, HALF_LENGTH + 0.4])
    frame_no = 0

    def blank_frames(n: int) -> None:
        nonlocal frame_no
        for _ in range(n):
            img = base.copy()
            draw_player(img, cam, near_pos[0], near_pos[1], (58, 58, 190))
            draw_player(img, cam, far_pos[0], far_pos[1], (190, 120, 40))
            writer.write(_noise(img, rng))
            frame_no += 1

    blank_frames(int(fps * 0.8))
    for idx, sp in enumerate(points):
        t_start = frame_no / fps
        frames, truth, t = simulate_point(sp, fps, t_start)
        for tr in truth:
            tr["point"] = idx
        truth_all.extend(truth)
        for fr in frames:
            p = fr["p"]
            img = base.copy()
            # 선수는 공의 지면 위치를 향해 천천히 이동
            target_near = np.array([np.clip(p[0], -6, 6), min(-1.0, -HALF_LENGTH + 1.2)])
            target_far = np.array([np.clip(p[0], -6, 6), max(1.0, HALF_LENGTH - 1.2)])
            if p[1] < 0:
                target_near = np.array([np.clip(p[0], -6.5, 6.5), np.clip(p[1] - 0.8, -HALF_LENGTH - 0.6, -1.0)])
            else:
                target_far = np.array([np.clip(p[0], -6.5, 6.5), np.clip(p[1] + 0.8, 1.0, HALF_LENGTH + 0.6)])
            near_pos = near_pos + (target_near - near_pos) * 0.10
            far_pos = far_pos + (target_far - far_pos) * 0.10
            draw_player(img, cam, near_pos[0], near_pos[1], (58, 58, 190))
            draw_player(img, cam, far_pos[0], far_pos[1], (190, 120, 40))
            u, v, z = cam.project(p)
            ball_frames[frame_no] = [round(u, 2), round(v, 2),
                                     round(float(p[0]), 3), round(float(p[1]), 3), round(float(p[2]), 3)]
            r = max(2, int(round(cam.f * 0.045 / z)))
            cv2.circle(img, (int(u), int(v)), r, BALL_COLOR, -1, cv2.LINE_AA)
            writer.write(_noise(img, rng))
            frame_no += 1
        point_meta.append({
            "index": idx, "server": sp.server, "court": sp.court,
            "outcome": sp.outcome, "shots": len(sp.shots),
            "t_start": round(t_start, 2), "t_end": round(frame_no / fps, 2),
        })
        blank_frames(int(fps * 1.6))     # 포인트 사이 인터벌

    writer.release()
    return {"fps": fps, "frames": frame_no, "size": [cam.width, cam.height],
            "camera": {"eye": list(cam.eye), "f": cam.f},
            "court_corners_image": _corner_pixels(cam),
            "points": point_meta, "truth": truth_all,
            "ball_frames": ball_frames}


NOISE_SIGMA = 1.0     # 센서 노이즈. 키우면 검출이 어려워지지만 인코딩 용량이 급증한다.


def _noise(img: np.ndarray, rng) -> np.ndarray:
    if NOISE_SIGMA <= 0:
        return img
    n = rng.normal(0, NOISE_SIGMA, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)


def _corner_pixels(cam: Camera) -> list[list[float]]:
    """수동 캘리브레이션에 그대로 쓸 수 있는 복식 코트 4모서리 픽셀 좌표."""
    corners = [(-DOUBLES_HALF_W, -HALF_LENGTH), (DOUBLES_HALF_W, -HALF_LENGTH),
               (DOUBLES_HALF_W, HALF_LENGTH), (-DOUBLES_HALF_W, HALF_LENGTH)]
    return [[round(cam.project((x, y, 0))[0], 2), round(cam.project((x, y, 0))[1], 2)]
            for x, y in corners]


def main() -> None:
    ap = argparse.ArgumentParser(description="합성 테니스 경기 영상 생성")
    ap.add_argument("--out", default="data/sample_match.webm")
    ap.add_argument("--points", type=int, default=8)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--noise", type=float, default=1.0, help="센서 노이즈 표준편차")
    args = ap.parse_args()

    global NOISE_SIGMA
    NOISE_SIGMA = args.noise
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    script = default_script(args.points, seed=args.seed)
    meta = render(str(out), script, fps=args.fps, seed=args.seed)
    meta_path = out.with_suffix(".truth.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"영상: {out}  ({meta['frames']} 프레임, {meta['frames'] / meta['fps']:.1f}초)")
    print(f"정답: {meta_path}")
    print(f"코트 4모서리 픽셀: {meta['court_corners_image']}")


if __name__ == "__main__":
    main()
