"""경기 통계 집계 + 코칭 리포트(강점/약점/드릴).

강점·약점을 "느낌"으로 뽑지 않는다. 지표마다 동호인 단식 기준값(mid)과
퍼짐(spread)을 두고 z = (값 - mid)/spread 를 계산해, 표본 수 조건을 만족한
지표만 줄 세워 상·하위를 고른다. 기준값은 `BENCHMARKS` 에서 리그/레벨별로
갈아 끼울 수 있게 한 곳에 모아 뒀다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from ..schema import PlayerTrack, PointRecord, Serializable, Shot, Side
from ..vision.players import coverage_metrics
from .shots import shots_of


# --- 기준값 ----------------------------------------------------------------
@dataclass(frozen=True)
class Benchmark:
    key: str
    label: str
    mid: float
    spread: float
    higher_is_better: bool = True
    min_samples: int = 6
    unit: str = ""
    drill: str = ""


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark("first_serve_in_pct", "퍼스트 서브 성공률", 0.58, 0.10, True, 10, "%",
              "서브 토스 높이를 일정하게 두고 10개씩 코스별(T/바디/와이드) 목표 연습"),
    Benchmark("first_serve_won_pct", "퍼스트 서브 득점률", 0.62, 0.10, True, 8, "%",
              "서브 후 첫 3구 패턴(서브+포핸드) 반복"),
    Benchmark("second_serve_won_pct", "세컨 서브 득점률", 0.48, 0.10, True, 6, "%",
              "스핀 서브로 바운스를 서비스라인 안쪽 깊게 넣는 연습"),
    Benchmark("double_fault_rate", "더블폴트 비율", 0.06, 0.04, False, 10, "%",
              "세컨 서브는 속도 70%로 낮추고 스핀량을 올려 성공률 90% 목표"),
    Benchmark("ace_rate", "에이스 비율", 0.04, 0.04, True, 10, "%", ""),
    Benchmark("return_won_pct", "리턴 득점률", 0.38, 0.10, True, 10, "%",
              "스플릿 스텝 타이밍 + 짧은 백스윙 블록 리턴 드릴"),
    Benchmark("winner_ue_ratio", "위너/언포스드 비율", 0.60, 0.35, True, 8, "",
              "랠리 10구 이상 이어가기 드릴로 무리한 공격 빈도 줄이기"),
    Benchmark("unforced_error_rate", "언포스드 에러 비율", 0.12, 0.05, False, 15, "%",
              "네트 위 1.5m 목표 크로스 랠리 20구 연속"),
    Benchmark("avg_depth_m", "평균 타구 깊이", 6.5, 1.5, True, 15, "m",
              "베이스라인 2m 안쪽 존에 떨어뜨리는 데스존 드릴"),
    Benchmark("fh_winner_rate", "포핸드 위너 비율", 0.08, 0.05, True, 12, "%", ""),
    Benchmark("bh_winner_rate", "백핸드 위너 비율", 0.05, 0.04, True, 12, "%", ""),
    Benchmark("fh_error_rate", "포핸드 에러 비율", 0.12, 0.06, False, 12, "%",
              "포핸드 인아웃 풋워크 + 히팅존 앞에서 잡기"),
    Benchmark("bh_error_rate", "백핸드 에러 비율", 0.14, 0.06, False, 12, "%",
              "백핸드 슬라이스로 안전하게 넘기는 옵션 추가"),
    Benchmark("net_won_pct", "네트 플레이 득점률", 0.60, 0.15, True, 5, "%",
              "어프로치 후 첫 발리 깊게 - 발리 대각 드릴"),
    Benchmark("net_approach_rate", "네트 접근 비율", 0.12, 0.08, True, 15, "%", ""),
    Benchmark("bp_save_pct", "브레이크포인트 방어율", 0.55, 0.18, True, 3, "%",
              "40-30/듀스 상황 시뮬레이션 서브 게임"),
    Benchmark("bp_convert_pct", "브레이크포인트 전환율", 0.42, 0.18, True, 3, "%",
              "리턴 게임 첫 구를 무조건 크로스 깊게 보내는 규칙 플레이"),
    Benchmark("long_rally_win_pct", "9구 이상 랠리 승률", 0.50, 0.14, True, 5, "%",
              "인터벌 러닝 + 20구 랠리 세트로 체력/집중 유지"),
    Benchmark("serve_speed_kmh", "서브 평균 구속(지면 투영)", 95.0, 20.0, True, 8, "km/h", ""),
    Benchmark("groundstroke_speed_kmh", "그라운드 스트로크 평균 구속", 70.0, 15.0, True, 15, "km/h", ""),
)

BENCHMARK_BY_KEY = {b.key: b for b in BENCHMARKS}


# --- 집계 ------------------------------------------------------------------
def _safe(n: float, d: float) -> Optional[float]:
    return float(n) / float(d) if d else None


@dataclass
class PlayerStats(Serializable):
    side: Side
    name: str = ""
    points_played: int = 0
    points_won: int = 0
    games_won: int = 0
    metrics: dict = field(default_factory=dict)      # key -> value (비율은 0~1)
    samples: dict = field(default_factory=dict)      # key -> 표본 수
    counts: dict = field(default_factory=dict)       # 원시 카운트 (표에 그대로 표시)
    distributions: dict = field(default_factory=dict)
    movement: dict = field(default_factory=dict)

    def win_pct(self) -> float:
        return self.points_won / self.points_played if self.points_played else 0.0


def compute_stats(
    side: Side,
    points: Sequence[PointRecord],
    shots: Sequence[Shot],
    player_track: Optional[PlayerTrack] = None,
    fps: float = 30.0,
    name: str = "",
) -> PlayerStats:
    st = PlayerStats(side=side, name=name)
    mine = shots_of(shots, side)
    st.points_played = len(points)
    st.points_won = sum(1 for p in points if p.winner_side == side)

    serve_points = [p for p in points if p.server_side == side]
    return_points = [p for p in points if p.server_side != side]
    serves = [s for s in mine if s.is_serve]

    aces = sum(1 for p in serve_points if p.end_reason == "ace")
    dfs = sum(1 for p in serve_points if p.end_reason == "double_fault")
    first_in = sum(1 for p in serve_points if p.serve_number == 1)
    first_won = sum(1 for p in serve_points if p.serve_number == 1 and p.winner_side == side)
    second_pts = sum(1 for p in serve_points if p.serve_number == 2)
    second_won = sum(1 for p in serve_points if p.serve_number == 2 and p.winner_side == side)

    ground = [s for s in mine if s.shot_type in ("forehand", "backhand", "return", "slice", "drop", "lob")]
    fh = [s for s in mine if s.shot_type == "forehand"]
    bh = [s for s in mine if s.shot_type == "backhand"]
    volleys = [s for s in mine if s.shot_type in ("volley", "overhead")]
    winners = [s for s in mine if s.result == "winner"]
    ue = [s for s in mine if s.result == "unforced_error"]
    fe = [s for s in mine if s.result == "forced_error"]

    net_points = {s.point_index for s in volleys}
    net_won = sum(1 for p in points if p.index in net_points and p.winner_side == side)

    bp_faced = [p for p in serve_points if p.is_break_point]
    bp_saved = [p for p in bp_faced if p.winner_side == side]
    bp_chance = [p for p in return_points if p.is_break_point]
    bp_conv = [p for p in bp_chance if p.winner_side == side]

    long_rallies = [p for p in points if p.rally_length >= 9]
    long_won = [p for p in long_rallies if p.winner_side == side]

    depths = [s.depth_m for s in ground if s.depth_m is not None]
    g_speeds = [s.speed_kmh for s in ground if s.speed_kmh]
    s_speeds = [s.speed_kmh for s in serves if s.speed_kmh]

    def put(key: str, value: Optional[float], n: int) -> None:
        if value is not None:
            st.metrics[key] = round(float(value), 4)
            st.samples[key] = int(n)

    put("first_serve_in_pct", _safe(first_in, len(serve_points)), len(serve_points))
    put("first_serve_won_pct", _safe(first_won, first_in), first_in)
    put("second_serve_won_pct", _safe(second_won, second_pts), second_pts)
    put("double_fault_rate", _safe(dfs, len(serve_points)), len(serve_points))
    put("ace_rate", _safe(aces, len(serve_points)), len(serve_points))
    put("return_won_pct", _safe(sum(1 for p in return_points if p.winner_side == side), len(return_points)),
        len(return_points))
    put("winner_ue_ratio", _safe(len(winners), len(ue)) if ue else (float(len(winners)) if winners else None),
        len(winners) + len(ue))
    put("unforced_error_rate", _safe(len(ue), len(mine)), len(mine))
    put("avg_depth_m", float(np.mean(depths)) if depths else None, len(depths))
    put("fh_winner_rate", _safe(sum(1 for s in fh if s.result == "winner"), len(fh)), len(fh))
    put("bh_winner_rate", _safe(sum(1 for s in bh if s.result == "winner"), len(bh)), len(bh))
    put("fh_error_rate", _safe(sum(1 for s in fh if s.result.endswith("error")), len(fh)), len(fh))
    put("bh_error_rate", _safe(sum(1 for s in bh if s.result.endswith("error")), len(bh)), len(bh))
    put("net_won_pct", _safe(net_won, len(net_points)), len(net_points))
    put("net_approach_rate", _safe(len(net_points), len(points)), len(points))
    put("bp_save_pct", _safe(len(bp_saved), len(bp_faced)), len(bp_faced))
    put("bp_convert_pct", _safe(len(bp_conv), len(bp_chance)), len(bp_chance))
    put("long_rally_win_pct", _safe(len(long_won), len(long_rallies)), len(long_rallies))
    put("serve_speed_kmh", float(np.mean(s_speeds)) if s_speeds else None, len(s_speeds))
    put("groundstroke_speed_kmh", float(np.mean(g_speeds)) if g_speeds else None, len(g_speeds))

    st.counts = {
        "servePoints": len(serve_points), "returnPoints": len(return_points),
        "aces": aces, "doubleFaults": dfs,
        "winners": len(winners), "unforcedErrors": len(ue), "forcedErrors": len(fe),
        "forehands": len(fh), "backhands": len(bh), "volleys": len(volleys),
        "netPoints": len(net_points), "netWon": net_won,
        "breakPointsFaced": len(bp_faced), "breakPointsSaved": len(bp_saved),
        "breakPointsHad": len(bp_chance), "breakPointsConverted": len(bp_conv),
        "totalShots": len(mine),
    }
    st.distributions = {
        "serveZones": _dist([s.serve_zone for s in serves if s.serve_zone]),
        "direction": _dist([s.direction for s in ground if s.direction]),
        "shotTypes": _dist([s.shot_type for s in mine]),
        "rallyBuckets": _rally_buckets(points, side),
        "bounceMap": [
            {"x": s.bounce_court_xy[0], "y": s.bounce_court_xy[1], "type": s.shot_type,
             "result": s.result}
            for s in mine if s.bounce_court_xy
        ],
    }
    if player_track is not None:
        st.movement = coverage_metrics(player_track, fps)
    return st


def _dist(values: Sequence[str]) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    total = sum(out.values()) or 1
    return {k: {"count": v, "pct": round(v / total, 3)} for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def _rally_buckets(points: Sequence[PointRecord], side: Side) -> dict:
    buckets = {"1-4": (1, 4), "5-8": (5, 8), "9+": (9, 10 ** 6)}
    out = {}
    for label, (lo, hi) in buckets.items():
        sel = [p for p in points if lo <= p.rally_length <= hi]
        won = sum(1 for p in sel if p.winner_side == side)
        out[label] = {"points": len(sel), "won": won,
                      "pct": round(won / len(sel), 3) if sel else None}
    return out


# --- 코칭 리포트 -----------------------------------------------------------
@dataclass
class Insight(Serializable):
    key: str
    label: str
    value: float
    display: str
    z: float
    samples: int
    drill: str = ""
    note: str = ""


@dataclass
class CoachReport(Serializable):
    side: Side
    name: str
    headline: str
    summary: str
    strengths: list[Insight] = field(default_factory=list)
    weaknesses: list[Insight] = field(default_factory=list)
    neutral: list[Insight] = field(default_factory=list)
    drills: list[str] = field(default_factory=list)
    data_confidence: float = 1.0


def _display(b: Benchmark, v: float) -> str:
    if b.unit == "%":
        return f"{v * 100:.0f}%"
    if b.unit:
        return f"{v:.1f}{b.unit}"
    return f"{v:.2f}"


def build_report(stats: PlayerStats, top_k: int = 3, data_confidence: float = 1.0) -> CoachReport:
    scored: list[Insight] = []
    for b in BENCHMARKS:
        if b.key not in stats.metrics:
            continue
        n = stats.samples.get(b.key, 0)
        if n < b.min_samples:
            continue
        v = stats.metrics[b.key]
        z = (v - b.mid) / b.spread
        if not b.higher_is_better:
            z = -z
        # 표본이 적으면 0 쪽으로 축소해 과잉 해석을 막는다
        shrink = n / (n + b.min_samples)
        scored.append(
            Insight(
                key=b.key, label=b.label, value=v, display=_display(b, v),
                z=round(float(z * shrink), 3), samples=n, drill=b.drill,
                note="" if shrink > 0.7 else "표본이 적어 참고용",
            )
        )
    scored.sort(key=lambda i: -i.z)
    strengths = [i for i in scored if i.z >= 0.4][:top_k]
    weaknesses = [i for i in reversed(scored) if i.z <= -0.4][:top_k]
    neutral = [i for i in scored if i not in strengths and i not in weaknesses]

    headline = _headline(stats, strengths, weaknesses)
    summary = _summary(stats, strengths, weaknesses)
    drills = [i.drill for i in weaknesses if i.drill]
    return CoachReport(
        side=stats.side, name=stats.name or stats.side, headline=headline, summary=summary,
        strengths=strengths, weaknesses=weaknesses, neutral=neutral, drills=drills,
        data_confidence=round(float(data_confidence), 3),
    )


def _headline(stats: PlayerStats, strengths, weaknesses) -> str:
    if strengths and weaknesses:
        return f"{strengths[0].label}으로 벌고 {weaknesses[0].label}에서 잃는다"
    if strengths:
        return f"{strengths[0].label}이 확실한 무기"
    if weaknesses:
        return f"{weaknesses[0].label}부터 손보면 승률이 오른다"
    return "표본이 더 필요하다"


def _summary(stats: PlayerStats, strengths, weaknesses) -> str:
    c = stats.counts
    parts = [
        f"{stats.points_played}포인트 중 {stats.points_won}포인트 획득"
        f"({stats.win_pct() * 100:.0f}%).",
        f"위너 {c.get('winners', 0)} / 언포스드 {c.get('unforcedErrors', 0)}.",
    ]
    if c.get("servePoints"):
        parts.append(f"서브 게임 {c['servePoints']}포인트, 에이스 {c.get('aces', 0)}, 더블폴트 {c.get('doubleFaults', 0)}.")
    if strengths:
        parts.append("강점: " + ", ".join(f"{i.label} {i.display}" for i in strengths) + ".")
    if weaknesses:
        parts.append("보완점: " + ", ".join(f"{i.label} {i.display}" for i in weaknesses) + ".")
    return " ".join(parts)


__all__ = [
    "Benchmark", "BENCHMARKS", "BENCHMARK_BY_KEY",
    "PlayerStats", "compute_stats", "Insight", "CoachReport", "build_report",
]
