"""엔진 전체가 공유하는 데이터 스키마.

여기 정의된 dataclass 들이 비전 -> 심판 -> 분석 -> 하이라이트 -> 서버(DB) -> 앱
으로 흐르는 단일 통화(currency)다. 서버 DB 테이블(server/models.py)과 앱의
TypeScript 타입(app/src/lib/types.js)은 이 스키마를 그대로 반영한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import numpy as np

Side = Literal["near", "far"]
CourtSide = Literal["deuce", "ad"]
CallKind = Literal["in", "out", "fault", "let", "not_up", "unknown"]
ShotType = Literal[
    "serve", "return", "forehand", "backhand", "volley", "overhead", "slice", "drop", "lob"
]
ShotResult = Literal["in_play", "winner", "forced_error", "unforced_error", "ace", "double_fault"]
EndReason = Literal[
    "winner", "unforced_error", "forced_error", "out", "net", "double_bounce",
    "ace", "double_fault", "manual",
]


def _default(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(f"직렬화 불가 타입: {type(o)}")


class Serializable:
    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=_default, ensure_ascii=False))

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)


# --- 비전 계층 -------------------------------------------------------------
@dataclass
class Detection(Serializable):
    """한 프레임에서의 검출 결과 (이미지 픽셀 좌표)."""

    frame: int
    x: float
    y: float
    confidence: float = 1.0
    w: float = 0.0
    h: float = 0.0
    source: str = "opencv"
    color_support: float = 0.0    # 0~1, 테니스공 색(형광 옐로우-그린) 일치도


@dataclass
class BallTrack(Serializable):
    """프레임별 공 위치. 결측 프레임은 None 으로 남긴다."""

    positions: list[Optional[tuple[float, float]]] = field(default_factory=list)
    confidence: list[float] = field(default_factory=list)
    fps: float = 30.0

    def __len__(self) -> int:
        return len(self.positions)

    def at(self, frame: int) -> Optional[tuple[float, float]]:
        if 0 <= frame < len(self.positions):
            return self.positions[frame]
        return None

    def detected_ratio(self) -> float:
        if not self.positions:
            return 0.0
        return sum(p is not None for p in self.positions) / len(self.positions)


@dataclass
class PlayerTrack(Serializable):
    """플레이어 한 명의 프레임별 발 위치(이미지 좌표) 및 코트 좌표."""

    side: Side
    positions: list[Optional[tuple[float, float]]] = field(default_factory=list)
    court_positions: list[Optional[tuple[float, float]]] = field(default_factory=list)

    def at(self, frame: int) -> Optional[tuple[float, float]]:
        if 0 <= frame < len(self.positions):
            return self.positions[frame]
        return None

    def court_at(self, frame: int) -> Optional[tuple[float, float]]:
        if 0 <= frame < len(self.court_positions):
            return self.court_positions[frame]
        return None


@dataclass
class Calibration(Serializable):
    """코트 캘리브레이션 결과."""

    homography: list[list[float]]
    image_points: list[tuple[float, float]]
    court_points: list[tuple[float, float]]
    landmark_names: list[str]
    reprojection_error_m: float
    method: Literal["manual", "auto"] = "manual"
    near_side_is_bottom: bool = True
    frame_size: tuple[int, int] = (0, 0)

    @property
    def H(self) -> np.ndarray:
        return np.asarray(self.homography, dtype=np.float64)

    def quality(self) -> str:
        e = self.reprojection_error_m
        if e < 0.03:
            return "excellent"
        if e < 0.08:
            return "good"
        if e < 0.20:
            return "fair"
        return "poor"


# --- 심판 계층 -------------------------------------------------------------
@dataclass
class BallEvent(Serializable):
    """공 궤적에서 검출된 이벤트(바운스 / 라켓 타격 / 네트)."""

    kind: Literal["bounce", "hit", "net", "out_of_play"]
    frame: int
    t: float
    image_xy: tuple[float, float]
    court_xy: Optional[tuple[float, float]] = None
    confidence: float = 0.0
    by_side: Optional[Side] = None          # hit 인 경우 친 사람의 사이드
    speed_kmh: Optional[float] = None


@dataclass
class LineCall(Serializable):
    """인/아웃 판정 1건. 챌린지 UI 가 이 객체를 그대로 그린다."""

    kind: CallKind
    confidence: float
    margin_cm: float                     # +면 라인 안쪽, -면 밖. 공 반지름 보정 포함
    court_xy: tuple[float, float]
    image_xy: tuple[float, float]
    region: str
    nearest_line: str
    frame: int
    t: float
    error_budget_cm: float               # 이 판정의 1시그마 불확실성
    too_close: bool = False              # 오차 예산 안이면 True (= 판독 불가)
    reason: str = ""

    def announce_ko(self) -> str:
        if self.too_close:
            return f"판독 불가 (라인에서 {abs(self.margin_cm):.0f}cm, 오차 ±{self.error_budget_cm:.0f}cm)"
        if self.kind == "out":
            return f"아웃 — {abs(self.margin_cm):.0f}cm"
        if self.kind == "fault":
            return f"폴트 — {abs(self.margin_cm):.0f}cm"
        if self.kind == "let":
            return "레트"
        return "인"


@dataclass
class Shot(Serializable):
    """샷 1개. 분석/코칭의 최소 단위."""

    index: int
    point_index: int
    player_side: Side
    shot_type: ShotType
    result: ShotResult
    t_start: float
    frame_start: int
    contact_court_xy: Optional[tuple[float, float]] = None
    bounce_court_xy: Optional[tuple[float, float]] = None
    speed_kmh: Optional[float] = None
    depth_m: Optional[float] = None          # 네트로부터의 바운스 거리
    lateral_m: Optional[float] = None        # 코트 중앙선에서의 좌우 이탈
    direction: Optional[str] = None          # cross / down_the_line / middle
    net_clearance_idx: Optional[float] = None
    is_serve: bool = False
    serve_number: Optional[int] = None       # 1 or 2
    serve_zone: Optional[str] = None         # T / body / wide
    rally_position: int = 0                  # 포인트 내 몇 번째 샷인가
    call: Optional[LineCall] = None


@dataclass
class PointRecord(Serializable):
    """포인트 1개의 결과 + 진행 중 스코어 스냅샷."""

    index: int
    server_side: Side
    court_side: CourtSide
    winner_side: Side
    end_reason: EndReason
    rally_length: int
    t_start: float
    t_end: float
    frame_start: int
    frame_end: int
    score_before: str = ""
    score_after: str = ""
    is_break_point: bool = False
    is_set_point: bool = False
    is_match_point: bool = False
    serve_number: int = 1
    shots: list[Shot] = field(default_factory=list)
    calls: list[LineCall] = field(default_factory=list)


@dataclass
class HighlightClip(Serializable):
    """자동 선정된 하이라이트 구간."""

    start: float
    end: float
    score: float
    tags: list[str] = field(default_factory=list)
    point_index: Optional[int] = None
    title: str = ""
    caption: str = ""
    clip_path: Optional[str] = None


@dataclass
class MatchAnalysis(Serializable):
    """한 경기 전체 분석 산출물 — 리포트/하이라이트/매칭이 전부 여기서 나온다."""

    match_id: str
    fps: float
    duration: float
    calibration: Optional[Calibration]
    points: list[PointRecord] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    calls: list[LineCall] = field(default_factory=list)
    highlights: list[HighlightClip] = field(default_factory=list)
    final_score: dict = field(default_factory=dict)
    player_names: dict[str, str] = field(default_factory=lambda: {"near": "P1", "far": "P2"})
    stats: dict = field(default_factory=dict)         # side -> PlayerStats.to_dict()
    reports: dict = field(default_factory=dict)       # side -> CoachReport.to_dict()
    styles: dict = field(default_factory=dict)        # side -> PlayStyle.to_dict()
    quality: dict = field(default_factory=dict)       # 추적/캘리브레이션 신뢰도
