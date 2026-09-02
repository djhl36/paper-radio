"""오프라인 전체 분석 파이프라인.

    영상 -> 캘리브레이션 -> 공/선수 추적 -> 이벤트 -> 심판(점수) -> 샷 분석
         -> 통계 -> 코칭 리포트 -> 플레이스타일 -> 하이라이트 -> MatchAnalysis

프레임을 한 번만 읽는다(공 추적과 선수 추적을 같은 루프에서 돌린다).
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .analytics import playstyle as ps_mod
from .analytics import report as report_mod
from .analytics import shots as shots_mod
from .highlights import select as hl
from .schema import Calibration, MatchAnalysis, PlayerTrack, Side
from .umpire import bounce as bounce_mod
from .umpire.rally import Umpire, UmpireConfig
from .umpire.scoring import MatchFormat, ScoreBoard
from .vision import court as court_mod
from .vision.ball import BallTracker, smooth_track, video_meta
from .vision.players import PlayerTracker

Progress = Callable[[str, float], None]


def _noop(stage: str, pct: float) -> None:
    pass


def calibrate_video(
    video_path: str, sample_frames: int = 8, image_points: Optional[list] = None,
    landmark_names: Optional[list] = None,
) -> Optional[Calibration]:
    """수동 점이 있으면 그걸로, 없으면 앞부분 프레임에서 자동 검출."""
    fps, n, size = video_meta(video_path)
    if image_points:
        return court_mod.calibrate_manual(
            image_points,
            landmark_names or list(court_mod.CALIBRATION_ORDER),  # type: ignore[attr-defined]
            frame_size=size,
        )
    cap = cv2.VideoCapture(video_path)
    frames = []
    try:
        total = n or 300
        idxs = np.linspace(0, max(total - 1, 0), sample_frames).astype(int)
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, f = cap.read()
            if ok:
                frames.append(f)
    finally:
        cap.release()
    if not frames:
        return None
    return court_mod.detect_court_stable(frames)


def analyze_match(
    video_path: str,
    calibration: Optional[Calibration] = None,
    match_format: str = "best_of_3",
    names: Optional[dict] = None,
    first_server_side: Side = "near",
    handedness: Optional[dict] = None,
    doubles: bool = False,
    out_dir: Optional[str] = None,
    cut_video_clips: bool = False,
    match_id: Optional[str] = None,
    progress: Progress = _noop,
    max_frames: Optional[int] = None,
) -> MatchAnalysis:
    t0 = time.time()
    names = {"near": "P1", "far": "P2", **(names or {})}
    match_id = match_id or uuid.uuid4().hex[:12]
    fps, n_frames, size = video_meta(video_path)

    progress("calibration", 0.02)
    calib = calibration or calibrate_video(video_path)
    if calib is None:
        raise RuntimeError(
            "코트를 자동으로 찾지 못했습니다. 앱에서 코트 4모서리를 지정한 뒤 다시 시도하세요."
        )

    # --- 1패스: 공 + 선수 추적 ------------------------------------------
    progress("tracking", 0.05)
    ball_tracker = BallTracker()
    player_tracker = PlayerTracker(calib, doubles=doubles)
    cap = cv2.VideoCapture(video_path)
    count = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ball_tracker.update(frame, count)
            player_tracker.update(frame, count)
            count += 1
            if max_frames and count >= max_frames:
                break
            if n_frames and count % 200 == 0:
                progress("tracking", 0.05 + 0.55 * min(count / n_frames, 1.0))
    finally:
        cap.release()

    total = count
    track = ball_tracker.to_track(total, fps)
    detected_ratio = track.detected_ratio()
    # 이벤트 검출에는 보간하지 않은 궤적을 쓴다. 결측 구간을 직선으로 메우면
    # 그 이음매가 가짜 속도 불연속(= 가짜 이벤트)을 만든다.
    track = smooth_track(track)
    players: dict[Side, PlayerTrack] = player_tracker.tracks

    # --- 이벤트 ----------------------------------------------------------
    progress("events", 0.62)
    events = bounce_mod.detect_events(track, calib, players)

    # --- 심판 ------------------------------------------------------------
    progress("umpire", 0.7)
    board = ScoreBoard(
        MatchFormat.preset(match_format),
        first_server="A",
        names={"A": names["near"] if first_server_side == "near" else names["far"],
               "B": names["far"] if first_server_side == "near" else names["near"]},
        first_server_side=first_server_side,
    )
    ump = Umpire(board, calib, track, UmpireConfig(doubles=doubles))
    points = ump.process_all(events)

    # --- 샷 / 통계 / 리포트 / 스타일 -------------------------------------
    progress("analytics", 0.8)
    shots = shots_mod.build_shots(points, ump.point_events, players, handedness, fps=fps)

    quality = _quality(detected_ratio, calib, points, ump.warnings)
    stats: dict = {}
    reports: dict = {}
    styles: dict = {}
    for side in ("near", "far"):
        s = report_mod.compute_stats(
            side, points, shots, players.get(side), fps=fps, name=names[side]  # type: ignore[arg-type]
        )
        stats[side] = s.to_dict()
        reports[side] = report_mod.build_report(s, data_confidence=quality["overall"]).to_dict()
        styles[side] = ps_mod.build_playstyle(s, names[side]).to_dict()

    # --- 하이라이트 ------------------------------------------------------
    progress("highlights", 0.9)
    duration = total / fps if fps else 0.0
    clips = hl.select_highlights(points, names=names, duration=duration)
    if cut_video_clips and out_dir:
        clips = hl.cut_clips(video_path, clips, str(Path(out_dir) / "clips"), prefix=match_id)

    analysis = MatchAnalysis(
        match_id=match_id,
        fps=fps,
        duration=round(duration, 2),
        calibration=calib,
        points=points,
        shots=shots,
        calls=ump.calls,
        highlights=clips,
        final_score=board.to_dict(),
        player_names=names,
        stats=stats,
        reports=reports,
        styles=styles,
        quality={**quality, "warnings": ump.warnings, "elapsed_s": round(time.time() - t0, 1)},
    )
    progress("done", 1.0)
    return analysis


def _quality(detected_ratio: float, calib: Calibration, points, warnings) -> dict:
    """이 분석을 얼마나 믿어도 되는지. 앱은 이 값으로 경고 배너를 띄운다."""
    calib_q = {"excellent": 1.0, "good": 0.85, "fair": 0.6, "poor": 0.3}[calib.quality()]
    track_q = float(min(1.0, detected_ratio / 0.55))
    point_q = float(min(1.0, len(points) / 20.0)) if points else 0.0
    warn_penalty = max(0.0, 1.0 - 0.05 * len(warnings))
    overall = round(float(calib_q * 0.35 + track_q * 0.4 + point_q * 0.15 + warn_penalty * 0.1), 3)
    return {
        "overall": overall,
        "calibration": calib.quality(),
        "calibrationErrorM": round(calib.reprojection_error_m, 4),
        "ballDetectionRatio": round(detected_ratio, 3),
        "pointsDetected": len(points),
        "usable": overall >= 0.5,
        "message": _quality_message(overall, calib, detected_ratio),
    }


def _quality_message(overall: float, calib: Calibration, ratio: float) -> str:
    if overall >= 0.8:
        return "분석 신뢰도 양호"
    tips = []
    if calib.quality() in ("fair", "poor"):
        tips.append("코트 4모서리를 다시 정확히 지정하세요")
    if ratio < 0.45:
        tips.append("공이 잘 안 잡혔습니다 — 더 밝은 환경/60fps/삼각대 고정 촬영을 권장합니다")
    if not tips:
        tips.append("포인트 수가 적어 통계 해석에 주의가 필요합니다")
    return " · ".join(tips)


def save_analysis(analysis: MatchAnalysis, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(analysis.to_json(indent=2), encoding="utf-8")
    return str(p)


__all__ = ["analyze_match", "calibrate_video", "save_analysis"]
