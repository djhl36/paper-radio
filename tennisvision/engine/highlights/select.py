"""하이라이트 자동 선정 및 클립 생성.

"기자" 역할. 포인트마다 재미 점수를 매기고 상위 구간을 잘라 낸다. 점수는
서로 다른 재미 요소를 정규화해 가중합한다.

    랠리 길이 · 마무리 방식(위너/에이스) · 압박 상황(브레이크/세트/매치 포인트)
    · 최고 구속 · 코스 변화 횟수 · 네트 플레이 · 라인 아슬아슬함 · 역전 여부

ffmpeg 이 있으면 실제 mp4 클립까지 만들고, 없으면 구간 정보만 돌려준다
(앱은 구간 정보만으로도 원본 영상에서 바로 재생할 수 있다).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ..schema import HighlightClip, PointRecord, Side


@dataclass
class HighlightConfig:
    max_clips: int = 12
    min_clips: int = 3          # 임계값을 못 넘어도 최소 이만큼은 뽑는다
    min_score: float = 0.35
    pre_roll_s: float = 2.5
    post_roll_s: float = 2.0
    min_gap_s: float = 1.0
    weights: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.weights is None:
            self.weights = {
                "rally": 0.22,
                "finish": 0.18,
                "pressure": 0.22,
                "speed": 0.12,
                "variety": 0.10,
                "net": 0.06,
                "close_call": 0.10,
            }


FINISH_SCORE = {
    "winner": 1.0, "ace": 0.85, "double_bounce": 0.7,
    "forced_error": 0.45, "out": 0.2, "net": 0.15,
    "unforced_error": 0.1, "double_fault": 0.05, "manual": 0.2,
}


def _norm(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return float(min(1.0, max(0.0, (x - lo) / (hi - lo))))


def score_point(pt: PointRecord, cfg: HighlightConfig) -> tuple[float, list[str]]:
    w = cfg.weights
    tags: list[str] = []

    rally = _norm(pt.rally_length, 2, 14)
    if pt.rally_length >= 10:
        tags.append(f"{pt.rally_length}구 랠리")

    finish = FINISH_SCORE.get(pt.end_reason, 0.2)
    if pt.end_reason == "winner":
        tags.append("위너")
    elif pt.end_reason == "ace":
        tags.append("에이스")

    pressure = 0.0
    if pt.is_break_point:
        pressure = max(pressure, 0.7)
        tags.append("브레이크 포인트")
    if pt.is_set_point:
        pressure = max(pressure, 0.9)
        tags.append("세트 포인트")
    if pt.is_match_point:
        pressure = 1.0
        tags.append("매치 포인트")

    speeds = [s.speed_kmh for s in pt.shots if s.speed_kmh]
    speed = _norm(max(speeds), 60, 140) if speeds else 0.0
    if speeds and max(speeds) >= 110:
        tags.append(f"{max(speeds):.0f}km/h")

    dirs = [s.direction for s in pt.shots if s.direction]
    changes = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
    variety = _norm(changes, 1, 6)

    net_shots = sum(1 for s in pt.shots if s.shot_type in ("volley", "overhead"))
    net = _norm(net_shots, 0, 3)
    if net_shots >= 2:
        tags.append("네트 플레이")

    close = 0.0
    for c in pt.calls:
        if abs(c.margin_cm) <= 12:
            close = max(close, 1.0 - abs(c.margin_cm) / 12.0)
    if close > 0.6:
        tags.append("라인 아슬아슬")

    score = (
        w["rally"] * rally + w["finish"] * finish + w["pressure"] * pressure
        + w["speed"] * speed + w["variety"] * variety + w["net"] * net
        + w["close_call"] * close
    )
    return round(float(score), 4), tags


def caption_ko(pt: PointRecord, tags: Sequence[str], names: dict) -> tuple[str, str]:
    winner = names.get(pt.winner_side, pt.winner_side)
    reason_ko = {
        "winner": "위너로 마무리", "ace": "에이스", "double_bounce": "상대가 못 받음",
        "out": "상대 아웃", "net": "상대 네트", "unforced_error": "상대 실책",
        "forced_error": "압박으로 유도한 실책", "double_fault": "더블폴트",
    }.get(pt.end_reason, pt.end_reason)
    title = f"{winner} — {tags[0] if tags else reason_ko}"
    caption = f"{pt.rally_length}구 랠리 끝에 {winner} {reason_ko}. 스코어 {pt.score_after or pt.score_before}"
    return title, caption


def select_highlights(
    points: Sequence[PointRecord],
    names: Optional[dict] = None,
    cfg: HighlightConfig | None = None,
    duration: Optional[float] = None,
    focus_side: Optional[Side] = None,
) -> list[HighlightClip]:
    """상위 포인트를 골라 클립 구간을 만든다.

    focus_side 를 주면 그 선수가 이긴 포인트에 가산점을 줘서 "내 하이라이트"를 만든다.
    """
    cfg = cfg or HighlightConfig()
    names = names or {"near": "P1", "far": "P2"}
    scored: list[tuple[float, PointRecord, list[str]]] = []
    for pt in points:
        s, tags = score_point(pt, cfg)
        if focus_side is not None:
            s = s * (1.25 if pt.winner_side == focus_side else 0.55)
        scored.append((s, pt, tags))

    scored.sort(key=lambda x: -x[0])

    def pick(threshold: float) -> list[tuple[float, PointRecord, list[str]]]:
        out: list[tuple[float, PointRecord, list[str]]] = []
        for s, pt, tags in scored:
            if s < threshold or len(out) >= cfg.max_clips:
                continue
            if any(abs(pt.t_start - c[1].t_start) < cfg.min_gap_s for c in out):
                continue
            out.append((s, pt, tags))
        return out

    chosen = pick(cfg.min_score)
    # 임계값을 넘는 포인트가 거의 없어도 "볼 게 없다"고 내놓지는 않는다.
    # 짧고 밋밋한 경기라도 그 안에서 제일 나은 장면은 보여 주는 게 맞다.
    if len(chosen) < cfg.min_clips and scored:
        chosen = pick(0.0)[: max(cfg.min_clips, len(chosen))]

    chosen.sort(key=lambda x: x[1].t_start)
    clips: list[HighlightClip] = []
    for s, pt, tags in chosen:
        start = max(0.0, pt.t_start - cfg.pre_roll_s)
        end = pt.t_end + cfg.post_roll_s
        if duration:
            end = min(end, duration)
        title, caption = caption_ko(pt, tags, names)
        clips.append(
            HighlightClip(
                start=round(start, 2), end=round(end, 2), score=round(min(s, 1.0), 4),
                tags=tags, point_index=pt.index, title=title, caption=caption,
            )
        )
    return clips


# --- 클립 렌더링 -----------------------------------------------------------
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def cut_clips(
    video_path: str, clips: Sequence[HighlightClip], out_dir: str, prefix: str = "clip"
) -> list[HighlightClip]:
    """각 구간을 mp4 로 잘라 저장하고 clip_path 를 채운다."""
    if not ffmpeg_available():
        return list(clips)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result: list[HighlightClip] = []
    for i, c in enumerate(clips):
        dest = out / f"{prefix}_{i:02d}.mp4"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{c.start:.2f}", "-i", video_path,
            "-t", f"{max(c.end - c.start, 0.5):.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=180)
            c.clip_path = str(dest)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            c.clip_path = None
        result.append(c)
    return result


def build_reel(clip_paths: Sequence[str], out_path: str) -> Optional[str]:
    """클립들을 하나의 하이라이트 영상으로 이어 붙인다."""
    paths = [p for p in clip_paths if p and Path(p).exists()]
    if not paths or not ffmpeg_available():
        return None
    listing = Path(out_path).with_suffix(".txt")
    listing.write_text("\n".join(f"file '{Path(p).as_posix()}'" for p in paths), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", "-movflags", "+faststart", out_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    finally:
        listing.unlink(missing_ok=True)
    return out_path


__all__ = [
    "HighlightConfig", "score_point", "select_highlights",
    "cut_clips", "build_reel", "ffmpeg_available",
]
