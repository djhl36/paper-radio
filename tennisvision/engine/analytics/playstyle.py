"""플레이 스타일 벡터와 아키타입.

분석 결과를 10차원 벡터(각 0~100)로 압축한다. 이 벡터가 분석 파트와 매칭
파트를 잇는 다리다.
  - 리포트  : 축별 막대/레이더로 "당신은 이런 선수" 를 보여준다.
  - 매칭    : 레이팅(실력)과 별개로 "어떤 상대와 붙으면 재미있는가" 를 계산한다.
  - 누적    : 경기마다 EWMA 로 갱신해 최신 폼을 반영한다.

축은 서로 독립적이지 않다(공격성과 파워는 상관이 크다). 그래도 사용자가
읽었을 때 바로 이해되는 축을 우선했고, 매칭 유사도에서는 축별 가중치로
중복을 눌러 준다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from ..schema import Serializable, Side
from .report import PlayerStats

AXES: tuple[str, ...] = (
    "aggression",       # 공격성
    "power",            # 파워
    "consistency",      # 안정성
    "net_play",         # 네트 플레이
    "serve",            # 서브
    "return_game",      # 리턴
    "variety",          # 구질 다양성
    "depth",            # 타구 깊이
    "movement",         # 활동량/커버력
    "forehand_bias",    # 포핸드 의존도
)

AXIS_LABELS_KO = {
    "aggression": "공격성",
    "power": "파워",
    "consistency": "안정성",
    "net_play": "네트 플레이",
    "serve": "서브",
    "return_game": "리턴",
    "variety": "구질 다양성",
    "depth": "타구 깊이",
    "movement": "활동량",
    "forehand_bias": "포핸드 의존도",
}

# 매칭 유사도에서 축별 가중치 (상관 높은 축은 낮춰 중복 반영을 줄인다)
AXIS_WEIGHTS = {
    "aggression": 1.0, "power": 0.7, "consistency": 1.0, "net_play": 1.0,
    "serve": 0.8, "return_game": 0.8, "variety": 0.9, "depth": 0.6,
    "movement": 0.8, "forehand_bias": 0.5,
}


def _scale(value: Optional[float], mid: float, spread: float, invert: bool = False) -> Optional[float]:
    """값을 0~100 으로. mid 가 50점, mid±2*spread 가 대략 5/95점."""
    if value is None:
        return None
    z = (value - mid) / (spread if spread else 1.0)
    if invert:
        z = -z
    return float(100.0 / (1.0 + math.exp(-0.9 * z)))


def _entropy(dist: dict) -> float:
    ps = [d["pct"] for d in dist.values() if d.get("pct")]
    if not ps:
        return 0.0
    return float(-sum(p * math.log(p + 1e-9) for p in ps) / math.log(len(ps) + 1e-9)) if len(ps) > 1 else 0.0


@dataclass
class PlayStyle(Serializable):
    side: Side
    name: str = ""
    vector: dict = field(default_factory=dict)       # 축 -> 0~100
    archetype: str = ""
    archetype_ko: str = ""
    archetype_scores: dict = field(default_factory=dict)
    confidence: float = 0.0
    tags: list[str] = field(default_factory=list)
    description: str = ""
    samples: int = 0

    def as_array(self) -> np.ndarray:
        return np.asarray([self.vector.get(a, 50.0) for a in AXES], dtype=float)


# --- 아키타입 --------------------------------------------------------------
ARCHETYPES: dict[str, dict] = {
    "aggressive_baseliner": {
        "ko": "공격형 베이스라이너",
        "centroid": {"aggression": 82, "power": 80, "consistency": 45, "net_play": 35,
                     "serve": 65, "return_game": 55, "variety": 45, "depth": 70,
                     "movement": 55, "forehand_bias": 72},
        "desc": "베이스라인에서 먼저 때려서 점수를 만든다. 위너도 많지만 에러도 같이 늘어난다.",
    },
    "counterpuncher": {
        "ko": "카운터펀처",
        "centroid": {"aggression": 30, "power": 40, "consistency": 82, "net_play": 25,
                     "serve": 45, "return_game": 72, "variety": 55, "depth": 62,
                     "movement": 82, "forehand_bias": 50},
        "desc": "상대가 무너질 때까지 받아 넘긴다. 긴 랠리와 리턴 게임에서 강하다.",
    },
    "serve_and_volley": {
        "ko": "서브 앤 발리어",
        "centroid": {"aggression": 75, "power": 65, "consistency": 50, "net_play": 88,
                     "serve": 82, "return_game": 45, "variety": 62, "depth": 55,
                     "movement": 60, "forehand_bias": 50},
        "desc": "서브를 넣고 바로 네트로 붙는다. 포인트를 짧게 끝내는 쪽이 유리하다.",
    },
    "big_server": {
        "ko": "빅 서버",
        "centroid": {"aggression": 68, "power": 78, "consistency": 48, "net_play": 45,
                     "serve": 92, "return_game": 35, "variety": 40, "depth": 58,
                     "movement": 42, "forehand_bias": 62},
        "desc": "서브 게임은 거의 안 내준다. 리턴 게임에서 한 번을 브레이크하느냐 싸움.",
    },
    "all_courter": {
        "ko": "올코트 플레이어",
        "centroid": {"aggression": 60, "power": 60, "consistency": 62, "net_play": 62,
                     "serve": 62, "return_game": 60, "variety": 72, "depth": 62,
                     "movement": 65, "forehand_bias": 55},
        "desc": "베이스라인과 네트를 상황에 따라 오간다. 약점이 적은 대신 압도적 무기도 적다.",
    },
    "grinder": {
        "ko": "그라인더",
        "centroid": {"aggression": 25, "power": 32, "consistency": 88, "net_play": 18,
                     "serve": 40, "return_game": 62, "variety": 42, "depth": 55,
                     "movement": 88, "forehand_bias": 48},
        "desc": "체력과 집중력으로 버틴다. 실책을 거의 안 하고 상대의 인내심을 시험한다.",
    },
    "crafty": {
        "ko": "변칙형",
        "centroid": {"aggression": 48, "power": 38, "consistency": 65, "net_play": 55,
                     "serve": 48, "return_game": 55, "variety": 90, "depth": 48,
                     "movement": 60, "forehand_bias": 45},
        "desc": "슬라이스·드롭·로브로 리듬을 깬다. 파워로 붙는 상대가 제일 싫어한다.",
    },
}


def build_playstyle(stats: PlayerStats, name: str = "") -> PlayStyle:
    """경기 통계 -> 스타일 벡터."""
    m = stats.metrics
    c = stats.counts
    d = stats.distributions
    total_shots = max(c.get("totalShots", 0), 1)
    points = max(stats.points_played, 1)

    winner_rate = c.get("winners", 0) / total_shots
    net_rate = m.get("net_approach_rate")
    short_rally_share = (d.get("rallyBuckets", {}).get("1-4", {}) or {}).get("points", 0) / points

    vec: dict[str, Optional[float]] = {
        "aggression": _scale(
            0.5 * winner_rate / 0.06 + 0.3 * (net_rate or 0.1) / 0.12 + 0.2 * short_rally_share / 0.55,
            1.0, 0.45,
        ),
        "power": _scale(m.get("groundstroke_speed_kmh"), 70.0, 15.0),
        "consistency": _scale(m.get("unforced_error_rate"), 0.12, 0.05, invert=True),
        "net_play": _scale(net_rate, 0.12, 0.08),
        "serve": _scale(
            _mix([(m.get("first_serve_in_pct"), 0.58, 0.10, 0.35),
                  (m.get("first_serve_won_pct"), 0.62, 0.10, 0.4),
                  (m.get("ace_rate"), 0.04, 0.04, 0.25)]),
            0.0, 1.0,
        ),
        "return_game": _scale(m.get("return_won_pct"), 0.38, 0.10),
        "variety": _scale(_entropy(d.get("shotTypes", {})), 0.55, 0.18),
        "depth": _scale(m.get("avg_depth_m"), 6.5, 1.5),
        "movement": _scale(
            (stats.movement.get("distance_m", 0.0) / max(points, 1)) if stats.movement else None,
            9.0, 4.0,
        ),
        "forehand_bias": _scale(
            _safe_ratio(c.get("forehands", 0), c.get("forehands", 0) + c.get("backhands", 0)),
            0.55, 0.13,
        ),
    }
    # 계산 불가한 축은 중립(50)으로 두되, 신뢰도를 깎는다
    known = sum(1 for v in vec.values() if v is not None)
    vector = {a: round(float(vec[a] if vec[a] is not None else 50.0), 1) for a in AXES}

    scores = _archetype_scores(vector)
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    margin = (ranked[0] - ranked[1]) if len(ranked) > 1 else 0.3
    sample_conf = min(1.0, points / 40.0)
    confidence = round(float(min(1.0, (known / len(AXES)) * sample_conf * (0.55 + margin))), 3)

    return PlayStyle(
        side=stats.side,
        name=name or stats.name,
        vector=vector,
        archetype=best,
        archetype_ko=ARCHETYPES[best]["ko"],
        archetype_scores={k: round(v, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])},
        confidence=confidence,
        tags=_tags(vector, stats),
        description=ARCHETYPES[best]["desc"],
        samples=points,
    )


def _safe_ratio(n: float, d: float) -> Optional[float]:
    return float(n) / float(d) if d else None


def _mix(items: Sequence[tuple[Optional[float], float, float, float]]) -> Optional[float]:
    """(값, mid, spread, 가중치) 들을 z 로 바꿔 가중평균."""
    zs, ws = [], []
    for v, mid, spread, w in items:
        if v is None:
            continue
        zs.append((v - mid) / (spread or 1.0))
        ws.append(w)
    if not zs:
        return None
    return float(np.average(zs, weights=ws))


def _archetype_scores(vector: dict) -> dict:
    """각 아키타입과의 유사도(0~1). 거리 -> 소프트맥스."""
    v = np.asarray([vector[a] for a in AXES], dtype=float)
    w = np.asarray([AXIS_WEIGHTS[a] for a in AXES], dtype=float)
    dists = {}
    for key, spec in ARCHETYPES.items():
        c = np.asarray([spec["centroid"][a] for a in AXES], dtype=float)
        dists[key] = float(np.sqrt(np.sum(w * (v - c) ** 2) / w.sum()))
    scores = {k: math.exp(-d / 18.0) for k, d in dists.items()}
    total = sum(scores.values()) or 1.0
    return {k: v / total for k, v in scores.items()}


def _tags(vector: dict, stats: PlayerStats) -> list[str]:
    tags: list[str] = []
    if vector["serve"] >= 70:
        tags.append("서브 강점")
    if vector["consistency"] >= 70:
        tags.append("에러 적음")
    if vector["aggression"] >= 70:
        tags.append("선제 공격")
    if vector["net_play"] >= 70:
        tags.append("네트 지향")
    if vector["movement"] >= 70:
        tags.append("수비 범위 넓음")
    if vector["variety"] >= 70:
        tags.append("구질 변화")
    if vector["forehand_bias"] >= 70:
        tags.append("포핸드 위주")
    elif vector["forehand_bias"] <= 32:
        tags.append("백핸드 자신감")
    if stats.counts.get("doubleFaults", 0) >= 5:
        tags.append("더블폴트 주의")
    return tags


# --- 스타일 간 관계 (매칭이 쓴다) ------------------------------------------
def style_similarity(a: PlayStyle | dict, b: PlayStyle | dict) -> float:
    """0~1. 1이면 같은 스타일."""
    va, vb = _vec(a), _vec(b)
    w = np.asarray([AXIS_WEIGHTS[x] for x in AXES], dtype=float)
    dist = float(np.sqrt(np.sum(w * (va - vb) ** 2) / w.sum()))
    return round(float(math.exp(-dist / 30.0)), 4)


def style_contrast(a: PlayStyle | dict, b: PlayStyle | dict) -> float:
    """0~1. 스타일 상성이 뚜렷할수록 높다(= 재미있는 매치)."""
    return round(1.0 - style_similarity(a, b), 4)


def matchup_note_ko(a: PlayStyle | dict, b: PlayStyle | dict) -> str:
    """두 스타일이 붙었을 때의 관전 포인트."""
    va, vb = _vec(a), _vec(b)
    idx = {x: i for i, x in enumerate(AXES)}
    notes = []
    if va[idx["net_play"]] > 65 and vb[idx["consistency"]] > 65:
        notes.append("네트 압박 대 패싱샷 싸움")
    if va[idx["power"]] > 65 and vb[idx["movement"]] > 65:
        notes.append("파워 대 수비 범위")
    if va[idx["serve"]] > 70 and vb[idx["return_game"]] > 65:
        notes.append("빅 서브 대 리턴 게임")
    if abs(va[idx["aggression"]] - vb[idx["aggression"]]) > 30:
        notes.append("템포 차이가 큰 매치")
    if not notes:
        notes.append("비슷한 스타일의 정면 승부")
    return " · ".join(notes)


def blend(prev: Optional[dict], new: PlayStyle, alpha: float = 0.35) -> dict:
    """누적 프로필 갱신 (EWMA). prev 는 이전 vector dict."""
    if not prev:
        return dict(new.vector)
    a = alpha * max(new.confidence, 0.2)
    return {k: round((1 - a) * float(prev.get(k, 50.0)) + a * float(new.vector.get(k, 50.0)), 1) for k in AXES}


def archetype_of_vector(vector: dict) -> tuple[str, str, dict]:
    scores = _archetype_scores({a: float(vector.get(a, 50.0)) for a in AXES})
    best = max(scores, key=scores.get)
    return best, ARCHETYPES[best]["ko"], {k: round(v, 3) for k, v in scores.items()}


def _vec(s: PlayStyle | dict) -> np.ndarray:
    d = s.vector if isinstance(s, PlayStyle) else s
    return np.asarray([float(d.get(a, 50.0)) for a in AXES], dtype=float)


__all__ = [
    "AXES", "AXIS_LABELS_KO", "AXIS_WEIGHTS", "ARCHETYPES",
    "PlayStyle", "build_playstyle", "style_similarity", "style_contrast",
    "matchup_note_ko", "blend", "archetype_of_vector",
]
