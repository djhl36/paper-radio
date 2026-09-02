"""분석 결과를 DB에 적재하고, 그 결과로 레이팅·스타일·누적 통계를 갱신한다.

이 모듈이 "분석 → 매칭" 순환의 이음매다. 경기 하나가 들어오면
    1) 포인트/샷/판정/하이라이트를 저장하고
    2) 선수별 누적 통계를 갱신해 커리어 강점·약점을 다시 뽑고
    3) 플레이스타일 벡터를 EWMA 로 이동시키고
    4) Glicko-2 레이팅을 갱신한다.
그 다음 매칭·리그는 이 세 값(레이팅/스타일/통계)만 보고 동작한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from engine.analytics import playstyle as ps_mod
from engine.analytics.report import PlayerStats, build_report
from engine.schema import MatchAnalysis

from . import ratings as rt
from .models import (
    CallRow,
    HighlightRow,
    Match,
    PlayerAggregate,
    PlayerRating,
    PointRow,
    ShotRow,
    StyleProfile,
    utcnow,
)


def _player_for_side(match: Match, side: str) -> Optional[int]:
    return match.near_player_id if side == "near" else match.far_player_id


def store_analysis(session: Session, match: Match, analysis: MatchAnalysis) -> Match:
    """분석 결과 전체를 DB에 반영한다(같은 경기를 다시 넣으면 덮어쓴다)."""
    _clear_existing(session, match.id)

    for pt in analysis.points:
        session.add(
            PointRow(
                match_id=match.id, idx=pt.index, server_side=pt.server_side,
                court_side=pt.court_side, winner_side=pt.winner_side,
                server_player_id=_player_for_side(match, pt.server_side),
                winner_player_id=_player_for_side(match, pt.winner_side),
                end_reason=pt.end_reason, rally_length=pt.rally_length,
                serve_number=pt.serve_number, is_break_point=pt.is_break_point,
                is_set_point=pt.is_set_point, is_match_point=pt.is_match_point,
                t_start=pt.t_start, t_end=pt.t_end,
                score_before=pt.score_before, score_after=pt.score_after,
            )
        )
    for s in analysis.shots:
        session.add(
            ShotRow(
                match_id=match.id, point_idx=s.point_index, idx=s.index,
                player_id=_player_for_side(match, s.player_side), player_side=s.player_side,
                shot_type=s.shot_type, result=s.result, t=s.t_start,
                speed_kmh=s.speed_kmh, depth_m=s.depth_m, lateral_m=s.lateral_m,
                direction=s.direction, serve_zone=s.serve_zone, serve_number=s.serve_number,
                rally_position=s.rally_position,
                bounce_x=s.bounce_court_xy[0] if s.bounce_court_xy else None,
                bounce_y=s.bounce_court_xy[1] if s.bounce_court_xy else None,
                contact_x=s.contact_court_xy[0] if s.contact_court_xy else None,
                contact_y=s.contact_court_xy[1] if s.contact_court_xy else None,
            )
        )
    point_of_frame = {p.index: p for p in analysis.points}
    for c in analysis.calls:
        pt_idx = next(
            (p.index for p in analysis.points if p.t_start - 1 <= c.t <= p.t_end + 1), -1
        )
        session.add(
            CallRow(
                match_id=match.id, point_idx=pt_idx, kind=c.kind, margin_cm=c.margin_cm,
                error_budget_cm=c.error_budget_cm, confidence=c.confidence,
                too_close=c.too_close, court_x=c.court_xy[0], court_y=c.court_xy[1],
                t=c.t, region=c.region, nearest_line=c.nearest_line,
            )
        )
    for h in analysis.highlights:
        pt = point_of_frame.get(h.point_index) if h.point_index is not None else None
        focus = _player_for_side(match, pt.winner_side) if pt else None
        session.add(
            HighlightRow(
                match_id=match.id, point_idx=h.point_index, start=h.start, end=h.end,
                score=h.score, title=h.title, caption=h.caption, tags=list(h.tags),
                clip_path=h.clip_path, focus_player_id=focus,
            )
        )

    match.status = "done"
    match.duration = analysis.duration
    match.fps = analysis.fps
    match.score_json = analysis.final_score
    match.quality = analysis.quality
    if analysis.calibration is not None:
        match.calibration = analysis.calibration.to_dict()
    snap = (analysis.final_score or {}).get("snapshot", {})
    winner_letter = snap.get("winner")
    if winner_letter:
        ends = snap.get("ends", {})
        side = ends.get(winner_letter)
        match.winner_player_id = _player_for_side(match, side) if side else None
    session.add(match)

    for side in ("near", "far"):
        pid = _player_for_side(match, side)
        if not pid:
            continue
        if analysis.stats.get(side):
            _apply_aggregate(session, pid, analysis.stats[side])
        if analysis.styles.get(side):
            _apply_style(session, pid, analysis.styles[side])

    _apply_ratings(session, match, analysis)
    session.commit()
    session.refresh(match)
    return match


def _clear_existing(session: Session, match_id: int) -> None:
    for model in (PointRow, ShotRow, CallRow, HighlightRow):
        for row in session.exec(select(model).where(model.match_id == match_id)).all():
            session.delete(row)
    session.flush()


# --- 누적 통계 -------------------------------------------------------------
def _apply_aggregate(session: Session, player_id: int, stats: dict) -> None:
    agg = session.get(PlayerAggregate, player_id) or PlayerAggregate(player_id=player_id)
    metrics = dict(agg.metrics or {})
    samples = dict(agg.samples or {})
    counts = dict(agg.counts or {})

    for key, value in (stats.get("metrics") or {}).items():
        n_new = int((stats.get("samples") or {}).get(key, 0))
        if n_new <= 0:
            continue
        n_old = int(samples.get(key, 0))
        old = float(metrics.get(key, value))
        metrics[key] = round((old * n_old + float(value) * n_new) / max(n_old + n_new, 1), 4)
        samples[key] = n_old + n_new
    for key, value in (stats.get("counts") or {}).items():
        if isinstance(value, (int, float)):
            counts[key] = counts.get(key, 0) + value

    agg.metrics = metrics
    agg.samples = samples
    agg.counts = counts
    agg.matches += 1
    agg.updated_at = utcnow()

    career = PlayerStats(
        side="near", name="", points_played=int(counts.get("servePoints", 0) + counts.get("returnPoints", 0)),
        points_won=0, metrics=metrics, samples=samples, counts=counts,
    )
    report = build_report(career, top_k=4, data_confidence=min(1.0, agg.matches / 5.0))
    agg.strengths = [i.to_dict() for i in report.strengths]
    agg.weaknesses = [i.to_dict() for i in report.weaknesses]
    session.add(agg)


# --- 스타일 ----------------------------------------------------------------
def _apply_style(session: Session, player_id: int, style: dict) -> None:
    prof = session.get(StyleProfile, player_id) or StyleProfile(player_id=player_id)
    from engine.analytics.playstyle import PlayStyle

    new = PlayStyle(
        side=style.get("side", "near"), name=style.get("name", ""),
        vector=style.get("vector", {}), archetype=style.get("archetype", ""),
        archetype_ko=style.get("archetype_ko", ""), confidence=float(style.get("confidence", 0.0)),
        tags=list(style.get("tags", [])), samples=int(style.get("samples", 0)),
    )
    prof.vector = ps_mod.blend(prof.vector, new)
    key, ko, _scores = ps_mod.archetype_of_vector(prof.vector)
    prof.archetype = key
    prof.archetype_ko = ko
    prof.matches += 1
    prof.confidence = round(min(1.0, 0.35 + 0.13 * prof.matches), 3)
    prof.tags = new.tags
    prof.updated_at = utcnow()
    session.add(prof)


# --- 레이팅 ----------------------------------------------------------------
def games_from_score(score_json: dict) -> tuple[int, int]:
    """최종 스코어에서 A/B 총 게임 수."""
    sets = score_json.get("sets") or []
    a = sum(int(s.get("games", {}).get("A", 0)) for s in sets)
    b = sum(int(s.get("games", {}).get("B", 0)) for s in sets)
    return a, b


def get_or_create_rating(session: Session, player_id: int) -> PlayerRating:
    row = session.get(PlayerRating, player_id)
    if row is None:
        row = PlayerRating(player_id=player_id)
        session.add(row)
        session.flush()
    return row


def _apply_ratings(session: Session, match: Match, analysis: MatchAnalysis) -> None:
    if match.rated or not match.near_player_id or not match.far_player_id:
        return
    snap = (analysis.final_score or {}).get("snapshot", {})
    if not snap.get("finished"):
        return  # 미완료 경기는 레이팅에 반영하지 않는다
    ends = snap.get("ends", {})
    letter_to_side = {letter: side for letter, side in ends.items()}
    ga, gb = games_from_score(analysis.final_score or {})
    winner_letter = snap.get("winner")
    if not winner_letter:
        return

    near_letter = next((l for l, s in letter_to_side.items() if s == "near"), "A")
    near_games = ga if near_letter == "A" else gb
    far_games = gb if near_letter == "A" else ga
    near_won = winner_letter == near_letter

    r_near = get_or_create_rating(session, match.near_player_id)
    r_far = get_or_create_rating(session, match.far_player_id)
    a = rt.Rating(r_near.rating, r_near.rd, r_near.vol)
    b = rt.Rating(r_far.rating, r_far.rd, r_far.vol)
    a2, b2 = rt.update_pair(a, b, near_games, far_games, near_won)

    for row, new, won in ((r_near, a2, near_won), (r_far, b2, not near_won)):
        row.rating = round(new.rating, 2)
        row.rd = round(new.rd, 2)
        row.vol = round(new.vol, 6)
        row.matches += 1
        row.wins += 1 if won else 0
        row.losses += 0 if won else 1
        row.peak_rating = max(row.peak_rating, row.rating)
        row.last_match_at = match.played_at
        row.updated_at = utcnow()
        session.add(row)

    match.rated = True
    session.add(match)


def apply_manual_result(
    session: Session, near_id: int, far_id: int, near_games: int, far_games: int, near_won: bool
) -> tuple[PlayerRating, PlayerRating]:
    """영상 없이 스코어만 입력한 경기(리그 walkover 등)의 레이팅 반영."""
    r_near = get_or_create_rating(session, near_id)
    r_far = get_or_create_rating(session, far_id)
    a = rt.Rating(r_near.rating, r_near.rd, r_near.vol)
    b = rt.Rating(r_far.rating, r_far.rd, r_far.vol)
    a2, b2 = rt.update_pair(a, b, near_games, far_games, near_won)
    for row, new, won in ((r_near, a2, near_won), (r_far, b2, not near_won)):
        row.rating = round(new.rating, 2)
        row.rd = round(new.rd, 2)
        row.vol = round(new.vol, 6)
        row.matches += 1
        row.wins += 1 if won else 0
        row.losses += 0 if won else 1
        row.peak_rating = max(row.peak_rating, row.rating)
        row.last_match_at = datetime.now(timezone.utc)
        row.updated_at = utcnow()
        session.add(row)
    session.commit()
    return r_near, r_far


__all__ = [
    "store_analysis", "apply_manual_result", "get_or_create_rating", "games_from_score",
]
