"""TennisVision API 서버.

  REST : 선수/경기/리포트/하이라이트/매칭/리그
  WS   : /ws/live/{session_id} — 폰이 프레임을 올리면 판정·점수를 되돌려준다
  정적 : app/dist 가 빌드돼 있으면 PWA 를 같이 서빙한다

실행:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import base64
import json
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

from engine.geometry import CALIBRATION_ORDER, LANDMARKS, LINE_SEGMENTS
from engine.pipeline import analyze_match, save_analysis
from engine.realtime import LiveConfig, LiveSession
from engine.schema import Calibration
from engine.vision.court import calibrate_manual, court_polygon_image, detect_court

from . import leagues as lg
from . import matching as mm
from . import ratings as rt
from .db import ANALYSIS_DIR, CLIP_DIR, UPLOAD_DIR, get_session, init_db, session_scope
from .ingest import store_analysis
from .models import (
    CallRow,
    HighlightRow,
    League,
    LeagueEntry,
    Match,
    MatchRequest,
    Player,
    PlayerAggregate,
    PlayerRating,
    PointRow,
    ShotRow,
    StyleProfile,
)

app = FastAPI(title="TennisVision API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

ANALYSIS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analyze")
JOBS: dict[int, dict] = {}          # match_id -> {stage, progress, error}
LIVE: dict[str, LiveSession] = {}   # session_id -> 진행 중인 실시간 세션


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ==========================================================================
# 스키마
# ==========================================================================
class PlayerIn(BaseModel):
    name: str
    email: Optional[str] = None
    handed: str = "right"
    backhand: str = "two"
    home_court: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    self_level: Optional[float] = None
    bio: str = ""


class CalibrationIn(BaseModel):
    imagePoints: list[list[float]]
    landmarks: Optional[list[str]] = None
    frameSize: Optional[list[int]] = None


class MatchRequestIn(BaseModel):
    playerId: int
    windowStart: datetime
    windowEnd: datetime
    court: Optional[str] = None
    maxDistanceKm: float = 15.0
    format: str = "one_set"
    intent: str = "competitive"
    stylePreference: str = "balanced"
    note: str = ""


class LeagueIn(BaseModel):
    name: str
    kind: str = "round_robin"
    court: Optional[str] = None
    ratingMin: Optional[float] = None
    ratingMax: Optional[float] = None
    maxPlayers: int = 16
    startsAt: Optional[datetime] = None
    description: str = ""


class FixtureResultIn(BaseModel):
    winnerId: int
    winnerGames: int
    loserGames: int
    matchId: Optional[int] = None


class ManualMatchIn(BaseModel):
    nearPlayerId: int
    farPlayerId: int
    nearGames: int
    farGames: int
    nearWon: bool
    court: Optional[str] = None


# ==========================================================================
# 코트 / 캘리브레이션
# ==========================================================================
@app.get("/api/court/model")
def court_model() -> dict:
    """앱이 코트를 그릴 때 쓰는 규격 정보."""
    return {
        "landmarks": {k: list(v) for k, v in LANDMARKS.items()},
        "calibrationOrder": list(CALIBRATION_ORDER),
        "lineSegments": [[list(a), list(b)] for a, b in LINE_SEGMENTS],
        "instructions": [
            "삼각대에 폰을 고정하고 베이스라인 뒤 높은 곳(2m 이상)에서 코트 전체가 보이게 촬영하세요.",
            "화면에서 복식 코트 4모서리를 좌하 → 우하 → 우상 → 좌상 순서로 탭하세요.",
            "가능하면 60fps 로 촬영하면 판정 정확도가 올라갑니다.",
        ],
    }


@app.post("/api/calibrate/manual")
def calibrate_endpoint(body: CalibrationIn) -> dict:
    try:
        calib = calibrate_manual(
            body.imagePoints, body.landmarks or list(CALIBRATION_ORDER),
            frame_size=tuple(body.frameSize or (0, 0)),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "calibration": calib.to_dict(),
        "quality": calib.quality(),
        "errorCm": round(calib.reprojection_error_m * 100, 2),
        "courtPolygon": court_polygon_image(calib),
        "overlay": _overlay_segments(calib),
    }


@app.post("/api/calibrate/auto")
async def calibrate_auto(frame: UploadFile = File(...)) -> dict:
    data = await frame.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "이미지를 읽을 수 없습니다")
    calib = detect_court(img)
    if calib is None:
        raise HTTPException(
            422, "코트를 자동으로 찾지 못했습니다. 4모서리를 직접 지정해 주세요."
        )
    return {
        "calibration": calib.to_dict(),
        "quality": calib.quality(),
        "corners": calib.image_points,
        "overlay": _overlay_segments(calib),
    }


def _overlay_segments(calib: Calibration) -> list[list[list[float]]]:
    from engine.geometry import court_to_image

    out = []
    for a, b in LINE_SEGMENTS:
        p1 = court_to_image(calib.H, *a)
        p2 = court_to_image(calib.H, *b)
        out.append([[round(p1[0], 1), round(p1[1], 1)], [round(p2[0], 1), round(p2[1], 1)]])
    return out


# ==========================================================================
# 선수
# ==========================================================================
@app.post("/api/players")
def create_player(body: PlayerIn, session: Session = Depends(get_session)) -> dict:
    player = Player(**body.model_dump())
    session.add(player)
    session.commit()
    session.refresh(player)
    session.add(PlayerRating(player_id=player.id))
    session.commit()
    return _player_summary(session, player)


@app.get("/api/players")
def list_players(
    q: Optional[str] = None, court: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    stmt = select(Player)
    if court:
        stmt = stmt.where(Player.home_court == court)
    players = session.exec(stmt).all()
    if q:
        players = [p for p in players if q.lower() in p.name.lower()]
    return [_player_summary(session, p) for p in players]


@app.get("/api/players/{player_id}")
def get_player(player_id: int, session: Session = Depends(get_session)) -> dict:
    player = session.get(Player, player_id)
    if player is None:
        raise HTTPException(404, "선수를 찾을 수 없습니다")
    agg = session.get(PlayerAggregate, player_id)
    prof = session.get(StyleProfile, player_id)
    matches = session.exec(
        select(Match).where(
            (Match.near_player_id == player_id) | (Match.far_player_id == player_id)
        )
    ).all()
    matches.sort(key=lambda m: m.played_at, reverse=True)
    highlights = session.exec(
        select(HighlightRow).where(HighlightRow.focus_player_id == player_id)
    ).all()
    highlights.sort(key=lambda h: -h.score)
    return {
        **_player_summary(session, player),
        "career": {
            "metrics": agg.metrics if agg else {},
            "counts": agg.counts if agg else {},
            "matches": agg.matches if agg else 0,
            "strengths": agg.strengths if agg else [],
            "weaknesses": agg.weaknesses if agg else [],
        },
        "style": {
            "vector": prof.vector if prof else {},
            "archetype": prof.archetype if prof else "",
            "archetypeKo": prof.archetype_ko if prof else "",
            "confidence": prof.confidence if prof else 0.0,
            "tags": prof.tags if prof else [],
            "matches": prof.matches if prof else 0,
        },
        "recentMatches": [_match_summary(session, m) for m in matches[:10]],
        "topHighlights": [_highlight_dict(h) for h in highlights[:8]],
    }


def _player_summary(session: Session, p: Player) -> dict:
    r = session.get(PlayerRating, p.id)
    rating = rt.Rating(r.rating, r.rd, r.vol) if r else rt.Rating()
    prof = session.get(StyleProfile, p.id)
    return {
        "id": p.id, "name": p.name, "handed": p.handed, "backhand": p.backhand,
        "homeCourt": p.home_court, "bio": p.bio, "selfLevel": p.self_level,
        "rating": round(rating.rating, 1), "rd": round(rating.rd, 1),
        "ntrp": rt.ntrp(rating.rating), "ratingConfidence": rt.confidence_label(rating.rd),
        "matches": r.matches if r else 0, "wins": r.wins if r else 0,
        "losses": r.losses if r else 0,
        "archetype": prof.archetype_ko if prof else None,
        "styleTags": prof.tags if prof else [],
    }


# ==========================================================================
# 경기 업로드 / 분석
# ==========================================================================
@app.post("/api/matches/upload")
async def upload_match(
    video: UploadFile = File(...),
    nearPlayerId: Optional[int] = Form(None),
    farPlayerId: Optional[int] = Form(None),
    format: str = Form("best_of_3"),
    firstServerSide: str = Form("near"),
    court: Optional[str] = Form(None),
    doubles: bool = Form(False),
    calibration: Optional[str] = Form(None),   # JSON: {"imagePoints": [[x,y]x4]}
    cutClips: bool = Form(False),
    session: Session = Depends(get_session),
) -> dict:
    public_id = uuid.uuid4().hex[:12]
    suffix = Path(video.filename or "match.mp4").suffix or ".mp4"
    dest = UPLOAD_DIR / f"{public_id}{suffix}"
    with dest.open("wb") as f:
        while chunk := await video.read(1 << 20):
            f.write(chunk)

    match = Match(
        public_id=public_id, source="upload", status="pending", format=format,
        doubles=doubles, court=court, near_player_id=nearPlayerId,
        far_player_id=farPlayerId, first_server_side=firstServerSide,
        video_path=str(dest),
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    calib_points = None
    if calibration:
        try:
            calib_points = json.loads(calibration).get("imagePoints")
        except json.JSONDecodeError:
            raise HTTPException(400, "calibration JSON 을 읽을 수 없습니다")

    JOBS[match.id] = {"stage": "queued", "progress": 0.0, "error": None}
    ANALYSIS_POOL.submit(_run_analysis, match.id, calib_points, cutClips)
    return {"matchId": match.id, "publicId": public_id, "status": "pending"}


def _run_analysis(match_id: int, calib_points: Optional[list], cut_clips: bool) -> None:
    def progress(stage: str, pct: float) -> None:
        JOBS[match_id] = {"stage": stage, "progress": round(pct, 3), "error": None}

    try:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if match is None or not match.video_path:
                return
            match.status = "analyzing"
            session.add(match)
            session.commit()

            names = _names_for(session, match)
            handed = _handedness_for(session, match)
            calib = None
            if calib_points:
                calib = calibrate_manual(calib_points, list(CALIBRATION_ORDER))

            analysis = analyze_match(
                match.video_path, calibration=calib, match_format=match.format,
                names=names, first_server_side=match.first_server_side,  # type: ignore[arg-type]
                handedness=handed, doubles=match.doubles,
                out_dir=str(CLIP_DIR), cut_video_clips=cut_clips,
                match_id=match.public_id, progress=progress,
            )
            path = ANALYSIS_DIR / f"{match.public_id}.json"
            save_analysis(analysis, str(path))
            match.analysis_path = str(path)
            store_analysis(session, match, analysis)
        JOBS[match_id] = {"stage": "done", "progress": 1.0, "error": None}
    except Exception as e:  # noqa: BLE001 - 작업 실패를 사용자에게 그대로 알린다
        JOBS[match_id] = {"stage": "failed", "progress": 0.0, "error": str(e)}
        traceback.print_exc()
        try:
            with session_scope() as session:
                match = session.get(Match, match_id)
                if match:
                    match.status = "failed"
                    match.error = str(e)
                    session.add(match)
        except Exception:
            pass


def _names_for(session: Session, match: Match) -> dict:
    near = session.get(Player, match.near_player_id) if match.near_player_id else None
    far = session.get(Player, match.far_player_id) if match.far_player_id else None
    return {"near": near.name if near else "니어", "far": far.name if far else "파"}


def _handedness_for(session: Session, match: Match) -> dict:
    near = session.get(Player, match.near_player_id) if match.near_player_id else None
    far = session.get(Player, match.far_player_id) if match.far_player_id else None
    return {"near": near.handed if near else "right", "far": far.handed if far else "right"}


@app.get("/api/matches/{match_id}/status")
def match_status(match_id: int, session: Session = Depends(get_session)) -> dict:
    match = session.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "경기를 찾을 수 없습니다")
    job = JOBS.get(match_id, {"stage": match.status, "progress": 1.0 if match.status == "done" else 0.0})
    return {"matchId": match_id, "status": match.status, **job}


@app.get("/api/matches")
def list_matches(
    playerId: Optional[int] = None, limit: int = 50, session: Session = Depends(get_session)
) -> list[dict]:
    stmt = select(Match)
    if playerId:
        stmt = stmt.where((Match.near_player_id == playerId) | (Match.far_player_id == playerId))
    matches = session.exec(stmt).all()
    matches.sort(key=lambda m: m.played_at, reverse=True)
    return [_match_summary(session, m) for m in matches[:limit]]


def _match_summary(session: Session, m: Match) -> dict:
    near = session.get(Player, m.near_player_id) if m.near_player_id else None
    far = session.get(Player, m.far_player_id) if m.far_player_id else None
    snap = (m.score_json or {}).get("snapshot", {})
    return {
        "id": m.id, "publicId": m.public_id, "status": m.status, "source": m.source,
        "format": m.format, "court": m.court,
        "playedAt": m.played_at.isoformat() if m.played_at else None,
        "duration": m.duration,
        "near": {"id": m.near_player_id, "name": near.name if near else "니어"},
        "far": {"id": m.far_player_id, "name": far.name if far else "파"},
        "winnerId": m.winner_player_id,
        "score": snap.get("scoreString", ""),
        "quality": m.quality,
        "hasVideo": bool(m.video_path and Path(m.video_path).exists()),
    }


@app.get("/api/matches/{match_id}")
def get_match(match_id: int, session: Session = Depends(get_session)) -> dict:
    match = session.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "경기를 찾을 수 없습니다")
    analysis = _load_analysis(match)
    points = session.exec(select(PointRow).where(PointRow.match_id == match_id)).all()
    calls = session.exec(select(CallRow).where(CallRow.match_id == match_id)).all()
    highlights = session.exec(select(HighlightRow).where(HighlightRow.match_id == match_id)).all()
    return {
        **_match_summary(session, match),
        "scoreDetail": match.score_json,
        "quality": match.quality,
        "points": [_point_dict(p) for p in sorted(points, key=lambda p: p.idx)],
        "calls": [_call_dict(c) for c in sorted(calls, key=lambda c: c.t)],
        "highlights": [_highlight_dict(h) for h in sorted(highlights, key=lambda h: -h.score)],
        "stats": (analysis or {}).get("stats", {}),
        "reports": (analysis or {}).get("reports", {}),
        "styles": (analysis or {}).get("styles", {}),
        "playerNames": (analysis or {}).get("player_names", {}),
        "hasVideo": bool(match.video_path and Path(match.video_path).exists()),
    }


def _load_analysis(match: Match) -> Optional[dict]:
    if not match.analysis_path:
        return None
    p = Path(match.analysis_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _point_dict(p: PointRow) -> dict:
    return {
        "idx": p.idx, "serverSide": p.server_side, "courtSide": p.court_side,
        "winnerSide": p.winner_side, "endReason": p.end_reason,
        "rallyLength": p.rally_length, "serveNumber": p.serve_number,
        "isBreakPoint": p.is_break_point, "isSetPoint": p.is_set_point,
        "isMatchPoint": p.is_match_point, "tStart": p.t_start, "tEnd": p.t_end,
        "scoreBefore": p.score_before, "scoreAfter": p.score_after,
    }


def _call_dict(c: CallRow) -> dict:
    return {
        "id": c.id, "pointIdx": c.point_idx, "kind": c.overridden_to or c.kind,
        "originalKind": c.kind, "marginCm": c.margin_cm,
        "errorBudgetCm": c.error_budget_cm, "confidence": c.confidence,
        "tooClose": c.too_close, "court": [c.court_x, c.court_y], "t": c.t,
        "region": c.region, "nearestLine": c.nearest_line,
        "overridden": c.overridden_to is not None,
    }


def _highlight_dict(h: HighlightRow) -> dict:
    return {
        "id": h.id, "matchId": h.match_id, "pointIdx": h.point_idx,
        "start": h.start, "end": h.end, "score": h.score,
        "title": h.title, "caption": h.caption, "tags": h.tags,
        "clipPath": h.clip_path, "hasClip": bool(h.clip_path),
    }


@app.get("/api/matches/{match_id}/shots")
def match_shots(
    match_id: int, playerId: Optional[int] = None, session: Session = Depends(get_session)
) -> list[dict]:
    stmt = select(ShotRow).where(ShotRow.match_id == match_id)
    if playerId:
        stmt = stmt.where(ShotRow.player_id == playerId)
    shots = session.exec(stmt).all()
    return [
        {
            "idx": s.idx, "pointIdx": s.point_idx, "playerId": s.player_id,
            "side": s.player_side, "type": s.shot_type, "result": s.result,
            "t": s.t, "speedKmh": s.speed_kmh, "depthM": s.depth_m,
            "lateralM": s.lateral_m, "direction": s.direction,
            "serveZone": s.serve_zone, "serveNumber": s.serve_number,
            "rallyPosition": s.rally_position,
            "bounce": [s.bounce_x, s.bounce_y] if s.bounce_x is not None else None,
            "contact": [s.contact_x, s.contact_y] if s.contact_x is not None else None,
        }
        for s in sorted(shots, key=lambda s: s.idx)
    ]


@app.post("/api/matches/{match_id}/calls/{call_id}/override")
def override_call(
    match_id: int, call_id: int, kind: str = Query(...), playerId: Optional[int] = None,
    session: Session = Depends(get_session),
) -> dict:
    call = session.get(CallRow, call_id)
    if call is None or call.match_id != match_id:
        raise HTTPException(404, "판정을 찾을 수 없습니다")
    if kind not in ("in", "out", "fault", "let", "unknown"):
        raise HTTPException(400, "허용되지 않는 판정 값입니다")
    call.overridden_to = kind
    call.overridden_by = playerId
    session.add(call)
    session.commit()
    return _call_dict(call)


@app.get("/api/matches/{match_id}/video")
def match_video(match_id: int, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if match is None or not match.video_path or not Path(match.video_path).exists():
        raise HTTPException(404, "영상이 없습니다")
    return FileResponse(match.video_path, media_type=_video_mime(match.video_path))


def _video_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4"}.get(ext, "video/mp4")


@app.get("/api/highlights/{highlight_id}/clip")
def highlight_clip(highlight_id: int, session: Session = Depends(get_session)):
    h = session.get(HighlightRow, highlight_id)
    if h is None or not h.clip_path or not Path(h.clip_path).exists():
        raise HTTPException(404, "클립이 없습니다")
    return FileResponse(h.clip_path, media_type="video/mp4")


@app.post("/api/matches/manual")
def manual_match(body: ManualMatchIn, session: Session = Depends(get_session)) -> dict:
    """영상 없이 스코어만 입력 (레이팅에는 반영된다)."""
    from .ingest import apply_manual_result

    match = Match(
        public_id=uuid.uuid4().hex[:12], source="upload", status="done",
        near_player_id=body.nearPlayerId, far_player_id=body.farPlayerId,
        court=body.court, rated=True,
        winner_player_id=body.nearPlayerId if body.nearWon else body.farPlayerId,
        score_json={"snapshot": {"scoreString": f"{body.nearGames}-{body.farGames}",
                                 "finished": True}},
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    apply_manual_result(
        session, body.nearPlayerId, body.farPlayerId,
        body.nearGames, body.farGames, body.nearWon,
    )
    return _match_summary(session, match)


# ==========================================================================
# 매칭
# ==========================================================================
@app.post("/api/matchmaking/requests")
def create_request(body: MatchRequestIn, session: Session = Depends(get_session)) -> dict:
    req = MatchRequest(
        player_id=body.playerId, window_start=body.windowStart, window_end=body.windowEnd,
        court=body.court, max_distance_km=body.maxDistanceKm, format=body.format,
        intent=body.intent, style_preference=body.stylePreference, note=body.note,
    )
    session.add(req)
    session.commit()
    session.refresh(req)
    return _request_dict(session, req)


@app.get("/api/matchmaking/requests")
def list_requests(
    playerId: Optional[int] = None, status: str = "open", session: Session = Depends(get_session)
) -> list[dict]:
    stmt = select(MatchRequest).where(MatchRequest.status == status)
    if playerId:
        stmt = stmt.where(MatchRequest.player_id == playerId)
    return [_request_dict(session, r) for r in session.exec(stmt).all()]


@app.delete("/api/matchmaking/requests/{request_id}")
def cancel_request(request_id: int, session: Session = Depends(get_session)) -> dict:
    req = session.get(MatchRequest, request_id)
    if req is None:
        raise HTTPException(404, "요청을 찾을 수 없습니다")
    req.status = "cancelled"
    session.add(req)
    session.commit()
    return {"ok": True}


def _request_dict(session: Session, r: MatchRequest) -> dict:
    p = session.get(Player, r.player_id)
    return {
        "id": r.id, "playerId": r.player_id, "playerName": p.name if p else "",
        "windowStart": r.window_start.isoformat(), "windowEnd": r.window_end.isoformat(),
        "court": r.court, "format": r.format, "intent": r.intent,
        "stylePreference": r.style_preference, "note": r.note, "status": r.status,
        "matchedWithId": r.matched_with_id,
    }


@app.get("/api/matchmaking/suggestions")
def suggestions(
    playerId: int, limit: int = 10, style: str = "balanced",
    maxDistanceKm: float = 20.0, session: Session = Depends(get_session),
) -> dict:
    cands = mm.suggest_opponents(
        session, playerId, limit=limit, style_preference=style, max_distance_km=maxDistanceKm
    )
    return {"weights": mm.WEIGHTS, "candidates": [c.to_dict() for c in cands]}


@app.post("/api/matchmaking/run")
def run_matchmaking(session: Session = Depends(get_session)) -> dict:
    made = mm.pair_open_requests(session)
    return {"matched": len(made), "pairs": made}


@app.get("/api/ladder")
def ladder(limit: int = 50, court: Optional[str] = None, session: Session = Depends(get_session)) -> list[dict]:
    return mm.ladder(session, limit=limit, court=court)


# ==========================================================================
# 리그
# ==========================================================================
@app.post("/api/leagues")
def create_league(body: LeagueIn, session: Session = Depends(get_session)) -> dict:
    league = lg.create_league(
        session, name=body.name, kind=body.kind, court=body.court,
        rating_min=body.ratingMin, rating_max=body.ratingMax,
        max_players=body.maxPlayers, starts_at=body.startsAt, description=body.description,
    )
    return _league_dict(session, league)


@app.get("/api/leagues")
def list_leagues(session: Session = Depends(get_session)) -> list[dict]:
    return [_league_dict(session, l) for l in session.exec(select(League)).all()]


def _league_dict(session: Session, l: League) -> dict:
    entries = session.exec(select(LeagueEntry).where(LeagueEntry.league_id == l.id)).all()
    return {
        "id": l.id, "name": l.name, "kind": l.kind, "status": l.status, "court": l.court,
        "ratingMin": l.rating_min, "ratingMax": l.rating_max, "maxPlayers": l.max_players,
        "players": len(entries), "description": l.description,
        "startsAt": l.starts_at.isoformat() if l.starts_at else None,
    }


@app.get("/api/leagues/{league_id}")
def league_detail(league_id: int, session: Session = Depends(get_session)) -> dict:
    league = session.get(League, league_id)
    if league is None:
        raise HTTPException(404, "리그를 찾을 수 없습니다")
    return {
        **_league_dict(session, league),
        "standings": lg.standings(session, league_id),
        "bracket": lg.bracket(session, league_id),
    }


@app.post("/api/leagues/{league_id}/join")
def join_league(league_id: int, playerId: int = Query(...), session: Session = Depends(get_session)) -> dict:
    try:
        lg.join_league(session, league_id, playerId)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return league_detail(league_id, session)


@app.post("/api/leagues/{league_id}/start")
def start_league(league_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        lg.start_league(session, league_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return league_detail(league_id, session)


@app.post("/api/fixtures/{fixture_id}/result")
def fixture_result(
    fixture_id: int, body: FixtureResultIn, session: Session = Depends(get_session)
) -> dict:
    try:
        fx = lg.record_result(
            session, fixture_id, body.winnerId, body.winnerGames, body.loserGames, body.matchId
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"fixtureId": fx.id, "status": fx.status, "winnerId": fx.winner_id,
            "score": fx.score_summary,
            "league": league_detail(fx.league_id, session)}


@app.get("/api/leagues/{league_id}/challenges")
def ladder_challenges(league_id: int, playerId: int, session: Session = Depends(get_session)) -> list[dict]:
    return lg.ladder_challenges(session, league_id, playerId)


# ==========================================================================
# 실시간 심판 (WebSocket)
# ==========================================================================
@app.websocket("/ws/live/{session_id}")
async def live_umpire(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    live: Optional[LiveSession] = LIVE.get(session_id)
    loop = asyncio.get_running_loop()

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("text") is not None:
                payload = json.loads(msg["text"])
                kind = payload.get("type")

                if kind == "init":
                    live = _init_live(session_id, payload)
                    LIVE[session_id] = live
                    await ws.send_json({"type": "ready", "status": live.status(),
                                        "overlay": _overlay_segments(live.calib)})
                    continue
                if live is None:
                    await ws.send_json({"type": "error", "message": "먼저 init 을 보내세요"})
                    continue

                if kind == "frame":                     # base64 JPEG (호환용 경로)
                    data = base64.b64decode(payload["data"].split(",")[-1])
                    out = await loop.run_in_executor(None, _push_bytes, live, data)
                    for m in out:
                        await ws.send_json(m)
                elif kind == "undo":
                    await ws.send_json(live.undo_point())
                elif kind == "award":
                    await ws.send_json(live.award_manual(payload.get("side", "near")))
                elif kind == "override":
                    await ws.send_json(live.override_call(int(payload["frame"]), payload["kind"]))
                elif kind == "serveNumber":
                    await ws.send_json(live.set_serve_number(int(payload.get("value", 1))))
                elif kind == "status":
                    await ws.send_json(live.status())
                elif kind == "finish":
                    result = await loop.run_in_executor(None, _finish_live, session_id, payload)
                    await ws.send_json(result)
                    break
                else:
                    await ws.send_json({"type": "error", "message": f"알 수 없는 요청: {kind}"})

            elif msg.get("bytes") is not None:
                if live is None:
                    await ws.send_json({"type": "error", "message": "먼저 init 을 보내세요"})
                    continue
                out = await loop.run_in_executor(None, _push_bytes, live, msg["bytes"])
                for m in out:
                    await ws.send_json(m)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


def _init_live(session_id: str, payload: dict) -> LiveSession:
    calib_payload = payload.get("calibration") or {}
    pts = calib_payload.get("imagePoints")
    if not pts:
        raise ValueError("calibration.imagePoints 가 필요합니다")
    calib = calibrate_manual(
        pts, calib_payload.get("landmarks") or list(CALIBRATION_ORDER),
        frame_size=tuple(calib_payload.get("frameSize") or (0, 0)),
    )
    cfg = LiveConfig(fps=float(payload.get("fps", 30.0)), doubles=bool(payload.get("doubles", False)))
    return LiveSession(
        calib, match_format=payload.get("format", "best_of_3"),
        names=payload.get("names"), first_server_side=payload.get("firstServerSide", "near"),
        cfg=cfg, session_id=session_id,
    )


def _push_bytes(live: LiveSession, data: bytes) -> list[dict]:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return [{"type": "error", "message": "프레임 디코딩 실패"}]
    return live.push_frame(img)


def _finish_live(session_id: str, payload: dict) -> dict:
    live = LIVE.pop(session_id, None)
    if live is None:
        return {"type": "error", "message": "세션이 없습니다"}
    analysis = live.finish()
    with session_scope() as session:
        match = Match(
            public_id=analysis.match_id, source="live", status="done",
            format=payload.get("format", "best_of_3"),
            near_player_id=payload.get("nearPlayerId"),
            far_player_id=payload.get("farPlayerId"),
            first_server_side=live.first_server_side, court=payload.get("court"),
        )
        session.add(match)
        session.commit()
        session.refresh(match)
        path = ANALYSIS_DIR / f"{analysis.match_id}.json"
        save_analysis(analysis, str(path))
        match.analysis_path = str(path)
        store_analysis(session, match, analysis)
        match_id = match.id
    return {"type": "finished", "matchId": match_id,
            "score": analysis.final_score.get("snapshot", {}),
            "points": len(analysis.points), "highlights": len(analysis.highlights)}


@app.get("/api/live/{session_id}/status")
def live_status(session_id: str) -> dict:
    live = LIVE.get(session_id)
    if live is None:
        raise HTTPException(404, "세션이 없습니다")
    return live.status()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "liveSessions": list(LIVE), "jobs": JOBS}


# ==========================================================================
# 정적 파일 (PWA)
# ==========================================================================
_DIST = Path(__file__).resolve().parents[1] / "app" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="app")
else:
    @app.get("/")
    def _no_app() -> JSONResponse:
        return JSONResponse({
            "message": "API 서버가 떠 있습니다. 앱을 보려면 app/ 에서 `npm install && npm run build` 하세요.",
            "docs": "/docs",
        })
