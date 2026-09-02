"""DB 스키마.

설계 의도: **분석과 매칭이 한 덩어리**가 되도록 만든다.

    Match(영상/라이브) ──분석──▶ Point / Shot / Call / Highlight
                                    │
                                    ├──▶ PlayerAggregate (누적 통계)
                                    ├──▶ StyleProfile   (플레이스타일 벡터, EWMA)
                                    └──▶ PlayerRating   (Glicko-2)
                                             │
                            MatchRequest ────┴──▶ 매칭 추천 ──▶ 새 Match
                            League/Fixture ──────────────────▶ 새 Match

즉 경기를 분석할 때마다 레이팅·스타일·통계가 갱신되고, 그 값이 곧바로 다음
매칭과 리그 시딩에 쓰인다. 한 방향으로만 흐르는 게 아니라 순환한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Index
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- 사용자 ---------------------------------------------------------------
class Player(SQLModel, table=True):
    __tablename__ = "player"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: Optional[str] = Field(default=None, index=True)
    handed: str = "right"                    # right | left
    backhand: str = "two"                    # one | two
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    home_court: Optional[str] = Field(default=None, index=True)
    lat: Optional[float] = None
    lon: Optional[float] = None
    self_level: Optional[float] = None        # 자가 신고 NTRP
    bio: str = ""
    avatar: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class PlayerRating(SQLModel, table=True):
    __tablename__ = "player_rating"

    player_id: int = Field(primary_key=True, foreign_key="player.id")
    rating: float = 1500.0
    rd: float = 350.0
    vol: float = 0.06
    matches: int = 0
    wins: int = 0
    losses: int = 0
    peak_rating: float = 1500.0
    last_match_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)


class StyleProfile(SQLModel, table=True):
    """누적 플레이스타일. 경기마다 EWMA 로 갱신된다."""

    __tablename__ = "style_profile"

    player_id: int = Field(primary_key=True, foreign_key="player.id")
    vector: dict = Field(default_factory=dict, sa_column=Column(JSON))
    archetype: str = ""
    archetype_ko: str = ""
    confidence: float = 0.0
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    matches: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


class PlayerAggregate(SQLModel, table=True):
    """커리어 누적 통계. 리포트의 '최근 대비' 비교와 매칭 필터에 쓴다."""

    __tablename__ = "player_aggregate"

    player_id: int = Field(primary_key=True, foreign_key="player.id")
    metrics: dict = Field(default_factory=dict, sa_column=Column(JSON))
    samples: dict = Field(default_factory=dict, sa_column=Column(JSON))
    counts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    strengths: list = Field(default_factory=list, sa_column=Column(JSON))
    weaknesses: list = Field(default_factory=list, sa_column=Column(JSON))
    matches: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


# --- 경기 -----------------------------------------------------------------
class Match(SQLModel, table=True):
    __tablename__ = "match"

    id: Optional[int] = Field(default=None, primary_key=True)
    public_id: str = Field(index=True)
    source: str = "upload"                    # upload | live
    status: str = Field(default="pending", index=True)  # pending|analyzing|done|failed
    format: str = "best_of_3"
    doubles: bool = False
    court: Optional[str] = None
    played_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)

    near_player_id: Optional[int] = Field(default=None, foreign_key="player.id", index=True)
    far_player_id: Optional[int] = Field(default=None, foreign_key="player.id", index=True)
    first_server_side: str = "near"
    winner_player_id: Optional[int] = Field(default=None, foreign_key="player.id")

    video_path: Optional[str] = None
    analysis_path: Optional[str] = None
    duration: float = 0.0
    fps: float = 30.0
    score_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    quality: dict = Field(default_factory=dict, sa_column=Column(JSON))
    calibration: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None
    fixture_id: Optional[int] = Field(default=None, foreign_key="fixture.id")
    rated: bool = False                       # 레이팅에 반영했는지


class PointRow(SQLModel, table=True):
    __tablename__ = "point"
    __table_args__ = (Index("ix_point_match_idx", "match_id", "idx"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    idx: int = 0
    server_side: str = "near"
    court_side: str = "deuce"
    winner_side: str = "near"
    server_player_id: Optional[int] = None
    winner_player_id: Optional[int] = None
    end_reason: str = ""
    rally_length: int = 0
    serve_number: int = 1
    is_break_point: bool = False
    is_set_point: bool = False
    is_match_point: bool = False
    t_start: float = 0.0
    t_end: float = 0.0
    score_before: str = ""
    score_after: str = ""


class ShotRow(SQLModel, table=True):
    __tablename__ = "shot"
    __table_args__ = (Index("ix_shot_match_player", "match_id", "player_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    point_idx: int = 0
    idx: int = 0
    player_id: Optional[int] = Field(default=None, index=True)
    player_side: str = "near"
    shot_type: str = ""
    result: str = ""
    t: float = 0.0
    speed_kmh: Optional[float] = None
    depth_m: Optional[float] = None
    lateral_m: Optional[float] = None
    direction: Optional[str] = None
    serve_zone: Optional[str] = None
    serve_number: Optional[int] = None
    rally_position: int = 0
    bounce_x: Optional[float] = None
    bounce_y: Optional[float] = None
    contact_x: Optional[float] = None
    contact_y: Optional[float] = None


class CallRow(SQLModel, table=True):
    """인/아웃 판정 기록. 챌린지(사용자 뒤집기) 이력도 여기 남는다."""

    __tablename__ = "call"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    point_idx: int = 0
    kind: str = "in"
    margin_cm: float = 0.0
    error_budget_cm: float = 0.0
    confidence: float = 0.0
    too_close: bool = False
    court_x: float = 0.0
    court_y: float = 0.0
    t: float = 0.0
    region: str = ""
    nearest_line: str = ""
    overridden_to: Optional[str] = None
    overridden_by: Optional[int] = None


class HighlightRow(SQLModel, table=True):
    __tablename__ = "highlight"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    point_idx: Optional[int] = None
    start: float = 0.0
    end: float = 0.0
    score: float = 0.0
    title: str = ""
    caption: str = ""
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    clip_path: Optional[str] = None
    focus_player_id: Optional[int] = Field(default=None, index=True)


# --- 매칭 -----------------------------------------------------------------
class MatchRequest(SQLModel, table=True):
    """'이 시간에 이 코트 근처에서 칠 사람 구함' 큐."""

    __tablename__ = "match_request"

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    window_start: datetime
    window_end: datetime
    court: Optional[str] = None
    max_distance_km: float = 15.0
    format: str = "one_set"
    intent: str = "competitive"           # competitive | practice | ladder
    style_preference: str = "balanced"    # similar | contrast | balanced
    note: str = ""
    status: str = Field(default="open", index=True)   # open | matched | expired | cancelled
    matched_with_id: Optional[int] = Field(default=None, foreign_key="player.id")
    match_id: Optional[int] = Field(default=None, foreign_key="match.id")


# --- 리그/대회 -------------------------------------------------------------
class League(SQLModel, table=True):
    __tablename__ = "league"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str = "round_robin"             # round_robin | single_elim | ladder
    status: str = Field(default="open", index=True)   # open | running | finished
    court: Optional[str] = None
    rating_min: Optional[float] = None
    rating_max: Optional[float] = None
    max_players: int = 16
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    description: str = ""


class LeagueEntry(SQLModel, table=True):
    __tablename__ = "league_entry"
    __table_args__ = (Index("ix_entry_league_player", "league_id", "player_id", unique=True),)

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="league.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    seed: int = 0
    points: int = 0
    wins: int = 0
    losses: int = 0
    games_won: int = 0
    games_lost: int = 0
    joined_at: datetime = Field(default_factory=utcnow)


class Fixture(SQLModel, table=True):
    __tablename__ = "fixture"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="league.id", index=True)
    round: int = 1
    slot: int = 0
    player1_id: Optional[int] = Field(default=None, foreign_key="player.id")
    player2_id: Optional[int] = Field(default=None, foreign_key="player.id")
    scheduled_at: Optional[datetime] = None
    court: Optional[str] = None
    status: str = "scheduled"             # scheduled | played | walkover | cancelled
    match_id: Optional[int] = None
    winner_id: Optional[int] = None
    score_summary: str = ""


class LiveSessionRow(SQLModel, table=True):
    """진행 중인 실시간 심판 세션(재접속/관전 지원용)."""

    __tablename__ = "live_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, unique=True)
    match_id: Optional[int] = Field(default=None, foreign_key="match.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    status: str = "active"                # active | finished | abandoned
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))


ALL_TABLES = [
    Player, PlayerRating, StyleProfile, PlayerAggregate,
    Match, PointRow, ShotRow, CallRow, HighlightRow,
    MatchRequest, League, LeagueEntry, Fixture, LiveSessionRow,
]
