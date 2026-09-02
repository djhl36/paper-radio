"""검출 과정을 눈으로 확인할 수 있게 영상 위에 그려서 다시 내보낸다.

그리는 것
  - 코트 모델 재투영 (캘리브레이션이 맞는지 한눈에)
  - 공 궤적 꼬리
  - 바운스 마커: 인/아웃 + 라인까지의 거리(cm) + 오차 예산
  - 타격 마커
  - 좌하단 미니맵: 지금까지의 바운스 누적
  - 우상단 패널: 스코어, 검출 통계
  - (정답 파일이 있으면) 실제 바운스 위치를 회색 X 로 함께 표시

정답을 같이 그리는 이유: 검출이 얼마나 맞고 얼마나 놓치는지 숫자가 아니라
장면으로 확인할 수 있어야 튜닝 방향이 잡힌다.

    python tools/annotate.py --video data/sample_match.webm --out data/annotated.webm
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.geometry import (  # noqa: E402
    CALIBRATION_ORDER,
    DOUBLES_HALF_W,
    HALF_LENGTH,
    LINE_SEGMENTS,
    court_to_image,
)
from engine.schema import Calibration  # noqa: E402
from engine.umpire import bounce as bounce_mod  # noqa: E402
from engine.umpire.rally import Umpire, UmpireConfig  # noqa: E402
from engine.umpire.scoring import MatchFormat, ScoreBoard  # noqa: E402
from engine.vision.ball import BallTracker, smooth_track, video_meta  # noqa: E402
from engine.vision.court import calibrate_manual, detect_court_stable  # noqa: E402
from engine.vision.players import PlayerTracker  # noqa: E402

WHITE = (255, 255, 255)
GREEN = (110, 230, 130)
RED = (110, 110, 250)
AMBER = (60, 190, 250)
CYAN = (240, 200, 80)
GREY = (150, 150, 150)
LIME = (74, 242, 214)

MARKER_HOLD_S = 1.8          # 마커를 화면에 유지하는 시간


def load_calibration(video: str, truth: Optional[dict], size) -> Calibration:
    if truth and truth.get("court_corners_image"):
        return calibrate_manual(truth["court_corners_image"], list(CALIBRATION_ORDER), frame_size=size)
    cap = cv2.VideoCapture(video)
    frames = []
    try:
        for _ in range(6):
            ok, f = cap.read()
            if ok:
                frames.append(f)
            for _ in range(30):
                cap.read()
    finally:
        cap.release()
    calib = detect_court_stable(frames)
    if calib is None:
        raise SystemExit("코트를 찾지 못했습니다. 정답 파일(.truth.json)을 함께 두거나 4모서리를 지정하세요.")
    return calib


def analyze(video: str, calib: Calibration, max_frames: Optional[int]):
    """추적 -> 이벤트 -> 심판. 그리기에 필요한 것만 돌려준다."""
    fps, _n, _size = video_meta(video)
    ball = BallTracker()
    players = PlayerTracker(calib)
    cap = cv2.VideoCapture(video)
    count = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ball.update(frame, count)
            players.update(frame, count)
            count += 1
            if max_frames and count >= max_frames:
                break
            if count % 300 == 0:
                print(f"  추적 {count} 프레임", end="\r")
    finally:
        cap.release()
    print()

    raw = ball.to_track(count, fps)
    detected_ratio = raw.detected_ratio()
    track = smooth_track(raw)
    events = bounce_mod.detect_events(track, calib, players.tracks)

    board = ScoreBoard(MatchFormat.preset("best_of_3"), first_server="A", first_server_side="near")
    ump = Umpire(board, calib, track, UmpireConfig())
    ump.process_all(events)
    return {
        "fps": fps, "frames": count, "track": track, "raw": raw,
        "events": events, "calls": ump.calls, "points": ump.points,
        "board": board, "detected_ratio": detected_ratio,
    }


def draw_court(img: np.ndarray, calib: Calibration) -> None:
    for a, b in LINE_SEGMENTS:
        p1 = court_to_image(calib.H, *a)
        p2 = court_to_image(calib.H, *b)
        cv2.line(img, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (80, 200, 220), 1, cv2.LINE_AA)


def minimap(bounces, w=190, h=330):
    """지금까지의 바운스 누적 미니맵."""
    pad = 10
    img = np.full((h, w, 3), 40, np.uint8)

    def to_map(x, y):
        return (
            int(pad + ((x + DOUBLES_HALF_W) / (2 * DOUBLES_HALF_W)) * (w - 2 * pad)),
            int(pad + ((HALF_LENGTH - y) / (2 * HALF_LENGTH)) * (h - 2 * pad)),
        )

    for a, b in LINE_SEGMENTS:
        cv2.line(img, to_map(*a), to_map(*b), (120, 150, 190), 1, cv2.LINE_AA)
    for (x, y, kind, close) in bounces:
        color = AMBER if close else (GREEN if kind == "in" else RED)
        cv2.circle(img, to_map(x, y), 3, color, -1, cv2.LINE_AA)
    return img


def panel(img, lines, x, y, w=330):
    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + 20 * len(lines) + 12), (25, 25, 35), -1)
    cv2.addWeighted(overlay, 0.62, img, 0.38, 0, img)
    for i, (text, color) in enumerate(lines):
        cv2.putText(img, text, (x + 10, y + 22 + 20 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)


def render(video: str, out: str, calib: Calibration, res: dict, truth: Optional[dict]) -> None:
    fps = res["fps"]
    track = res["track"]
    hold = int(MARKER_HOLD_S * fps)

    call_by_frame = {c.frame: c for c in res["calls"]}
    hit_frames = {e.frame for e in res["events"] if e.kind == "hit"}
    point_by_frame = {p.frame_end: p for p in res["points"]}

    truth_bounces = []
    if truth:
        truth_bounces = [
            (int(round(e["t"] * fps)), e["x"], e["y"])
            for e in truth.get("truth", []) if e["kind"] == "bounce"
        ]
    truth_by_frame: dict[int, list] = {}
    for f, x, y in truth_bounces:
        truth_by_frame.setdefault(f, []).append((x, y))

    cap = cv2.VideoCapture(video)
    ok, first = cap.read()
    if not ok:
        raise SystemExit("영상을 읽을 수 없습니다")
    h, w = first.shape[:2]
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    fourcc = "VP80" if out.lower().endswith(".webm") else "mp4v"
    writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))
    if not writer.isOpened():
        raise SystemExit(f"출력 파일을 열 수 없습니다 (코덱 {fourcc})")

    seen_bounces: list[tuple[float, float, str, bool]] = []
    score_text = "0-0"
    n_in = n_out = n_close = 0
    idx = 0
    try:
        while idx < res["frames"]:
            ok, frame = cap.read()
            if not ok:
                break
            draw_court(frame, calib)

            # 궤적 꼬리
            trail = [track.at(k) for k in range(max(0, idx - 18), idx + 1)]
            prev = None
            for j, p in enumerate(trail):
                if p is None:
                    prev = None
                    continue
                if prev is not None:
                    a = (j + 1) / len(trail)
                    cv2.line(frame, (int(prev[0]), int(prev[1])), (int(p[0]), int(p[1])),
                             (int(240 * a), int(200 * a), int(80 * a)), max(1, int(1 + 2 * a)), cv2.LINE_AA)
                prev = p
            cur = track.at(idx)
            if cur is not None:
                cv2.circle(frame, (int(cur[0]), int(cur[1])), 5, LIME, -1, cv2.LINE_AA)

            # 정답 바운스 (회색 X)
            for f0 in range(max(0, idx - hold), idx + 1):
                for (tx, ty) in truth_by_frame.get(f0, []):
                    ix, iy = court_to_image(calib.H, tx, ty)
                    ix, iy = int(ix), int(iy)
                    cv2.line(frame, (ix - 7, iy - 7), (ix + 7, iy + 7), GREY, 2, cv2.LINE_AA)
                    cv2.line(frame, (ix - 7, iy + 7), (ix + 7, iy - 7), GREY, 2, cv2.LINE_AA)

            # 타격 마커
            for f0 in range(max(0, idx - hold // 2), idx + 1):
                if f0 in hit_frames:
                    p = track.at(f0)
                    if p:
                        cv2.circle(frame, (int(p[0]), int(p[1])), 13, CYAN, 1, cv2.LINE_AA)

            # 바운스 판정 마커
            for f0 in range(max(0, idx - hold), idx + 1):
                c = call_by_frame.get(f0)
                if c is None:
                    continue
                if f0 == idx:
                    kind = "in" if c.kind == "in" else "out"
                    seen_bounces.append((c.court_xy[0], c.court_xy[1], kind, c.too_close))
                    if c.too_close:
                        n_close += 1
                    elif c.kind == "in":
                        n_in += 1
                    else:
                        n_out += 1
                age = (idx - f0) / max(hold, 1)
                color = AMBER if c.too_close else (GREEN if c.kind == "in" else RED)
                ix, iy = int(c.image_xy[0]), int(c.image_xy[1])
                r = int(14 + 22 * (1 - age) ** 2)
                cv2.circle(frame, (ix, iy), r, color, 2, cv2.LINE_AA)
                cv2.circle(frame, (ix, iy), 3, color, -1, cv2.LINE_AA)
                label = "TOO CLOSE" if c.too_close else ("IN" if c.kind == "in" else c.kind.upper())
                cv2.putText(frame, label, (ix + r + 6, iy - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
                cv2.putText(frame, f"{abs(c.margin_cm):.0f}cm  +/-{c.error_budget_cm:.0f}cm",
                            (ix + r + 6, iy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

            pt = point_by_frame.get(idx)
            if pt is not None:
                score_text = pt.score_after or score_text

            # 패널
            panel(frame, [
                (f"score  {score_text}", WHITE),
                (f"ball detected  {res['detected_ratio'] * 100:.0f}%", WHITE),
                (f"calls  IN {n_in}  OUT {n_out}  CLOSE {n_close}", WHITE),
                ("grey X = ground truth bounce" if truth else "", GREY),
            ], w - 350, 14)

            mm = minimap(seen_bounces[-400:])
            mh, mw = mm.shape[:2]
            frame[h - mh - 14:h - 14, 14:14 + mw] = mm

            writer.write(frame)
            idx += 1
            if idx % 300 == 0:
                print(f"  렌더 {idx}/{res['frames']}", end="\r")
    finally:
        cap.release()
        writer.release()
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="검출 결과를 영상 위에 그려서 내보낸다")
    ap.add_argument("--video", default="data/sample_match.webm")
    ap.add_argument("--out", default="data/annotated.webm")
    ap.add_argument("--max-frames", type=int, default=None)
    args = ap.parse_args()

    video = Path(args.video)
    truth_path = video.with_suffix(".truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else None

    fps, n, size = video_meta(str(video))
    calib = load_calibration(str(video), truth, size)
    print(f"캘리브레이션 {calib.quality()} (오차 {calib.reprojection_error_m * 100:.2f}cm)")

    res = analyze(str(video), calib, args.max_frames)
    print(f"공 검출률 {res['detected_ratio'] * 100:.1f}% · 이벤트 {len(res['events'])} · "
          f"판정 {len(res['calls'])} · 포인트 {len(res['points'])}")

    render(str(video), args.out, calib, res, truth)
    print(f"완료: {args.out}")


if __name__ == "__main__":
    main()
