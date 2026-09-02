"""매칭 엔진.

"비슷한 수준"만 보면 매칭이 지루해진다. 실제로 다시 치고 싶어지는 매치는
    (1) 스코어가 팽팽하고, (2) 시간·장소가 맞고, (3) 스타일이 물리거나 새롭고,
    (4) 매번 같은 사람이 아닌
매치다. 그래서 점수를 네 축으로 쪼개고, 각 축의 기여도를 사용자에게 그대로
보여 준다(왜 이 사람을 추천했는지 설명 가능해야 한다).

레이팅은 Glicko-2 라 불확실성을 포함한 승률 예측이 나오고, 스타일은 분석
파이프라인이 만든 10차원 벡터를 쓴다. 즉 매칭 품질은 경기를 분석할수록 좋아진다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlmodel import Session, select

from engine.analytics import playstyle as ps_mod

from . import ratings as rt
from .models import Match, MatchRequest, Player, PlayerRating, StyleProfile

WEIGHTS = {
    "competitiveness": 0.42,
    "availability": 0.20,
    "proximity": 0.15,
    "style": 0.13,
    "novelty": 0.10,
}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@dataclass
class Candidate:
    player_id: int
    name: str
    rating: float
    rd: float
    ntrp: float
    confidence: str
    archetype_ko: str
    total: float
    parts: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    predicted: str = ""
    matchup_note: str = ""
    distance_km: Optional[float] = None
    overlap_hours: float = 0.0
    played_before: int = 0

    def to_dict(self) -> dict:
        return {
            "playerId": self.player_id, "name": self.name,
            "rating": round(self.rating, 1), "rd": round(self.rd, 1),
            "ntrp": self.ntrp, "ratingConfidence": self.confidence,
            "archetype": self.archetype_ko, "score": round(self.total, 4),
            "parts": {k: round(v, 3) for k, v in self.parts.items()},
            "reasons": self.reasons, "predicted": self.predicted,
            "matchupNote": self.matchup_note,
            "distanceKm": round(self.distance_km, 1) if self.distance_km is not None else None,
            "overlapHours": round(self.overlap_hours, 1),
            "playedBefore": self.played_before,
        }


def _rating_of(session: Session, player_id: int) -> rt.Rating:
    row = session.get(PlayerRating, player_id)
    if row is None:
        return rt.Rating()
    return rt.Rating(row.rating, row.rd, row.vol)


def _style_of(session: Session, player_id: int) -> Optional[dict]:
    prof = session.get(StyleProfile, player_id)
    return prof.vector if prof and prof.vector else None


def _overlap_hours(a_start, a_end, b_start, b_end) -> float:
    a_start, a_end = _aware(a_start), _aware(a_end)
    b_start, b_end = _aware(b_start), _aware(b_end)
    if not all((a_start, a_end, b_start, b_end)):
        return 0.0
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    return max((hi - lo).total_seconds() / 3600.0, 0.0)


def _history_count(session: Session, a: int, b: int, days: int = 90) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.exec(
        select(Match).where(
            ((Match.near_player_id == a) & (Match.far_player_id == b))
            | ((Match.near_player_id == b) & (Match.far_player_id == a))
        )
    ).all()
    return sum(1 for m in rows if (_aware(m.played_at) or since) >= since)


def suggest_opponents(
    session: Session,
    player_id: int,
    limit: int = 10,
    style_preference: str = "balanced",
    window: Optional[tuple[datetime, datetime]] = None,
    max_distance_km: float = 20.0,
    min_score: float = 0.0,
    exclude: Sequence[int] = (),
) -> list[Candidate]:
    me = session.get(Player, player_id)
    if me is None:
        return []
    my_rating = _rating_of(session, player_id)
    my_style = _style_of(session, player_id)

    my_requests = session.exec(
        select(MatchRequest).where(
            MatchRequest.player_id == player_id, MatchRequest.status == "open"
        )
    ).all()
    if window is None and my_requests:
        window = (my_requests[0].window_start, my_requests[0].window_end)

    others = session.exec(select(Player).where(Player.id != player_id)).all()
    open_requests = session.exec(
        select(MatchRequest).where(MatchRequest.status == "open")
    ).all()
    req_by_player: dict[int, list[MatchRequest]] = {}
    for r in open_requests:
        req_by_player.setdefault(r.player_id, []).append(r)

    out: list[Candidate] = []
    for other in others:
        if other.id in exclude:
            continue
        r_other = _rating_of(session, other.id)
        parts: dict[str, float] = {}
        reasons: list[str] = []

        # 1) 팽팽함
        comp = rt.competitiveness(my_rating, r_other)
        parts["competitiveness"] = comp
        p = rt.expected_score(my_rating, r_other)
        if comp > 0.8:
            reasons.append(f"실력이 거의 같습니다 (예상 승률 {p * 100:.0f}%)")
        elif p > 0.72:
            reasons.append("한 수 아래 상대 — 연습 상대로 적당")
        elif p < 0.28:
            reasons.append("한 수 위 상대 — 도전해볼 만함")

        # 2) 시간대
        overlap = 0.0
        if window:
            for r in req_by_player.get(other.id, []):
                overlap = max(overlap, _overlap_hours(window[0], window[1], r.window_start, r.window_end))
        parts["availability"] = min(overlap / 2.0, 1.0) if window else 0.4
        if overlap >= 1.0:
            reasons.append(f"가능 시간 {overlap:.0f}시간 겹침")

        # 3) 거리
        dist = None
        if me.lat is not None and me.lon is not None and other.lat is not None and other.lon is not None:
            dist = haversine_km(me.lat, me.lon, other.lat, other.lon)
            parts["proximity"] = max(0.0, 1.0 - dist / max(max_distance_km, 1.0))
            if dist <= 5:
                reasons.append(f"{dist:.1f}km 거리")
        elif me.home_court and other.home_court and me.home_court == other.home_court:
            parts["proximity"] = 1.0
            reasons.append(f"같은 코트({me.home_court}) 이용")
        else:
            parts["proximity"] = 0.35

        # 4) 스타일
        other_style = _style_of(session, other.id)
        note = ""
        if my_style and other_style:
            sim = ps_mod.style_similarity(my_style, other_style)
            if style_preference == "similar":
                parts["style"] = sim
            elif style_preference == "contrast":
                parts["style"] = 1.0 - sim
            else:
                # 너무 같지도 너무 다르지도 않을 때가 제일 재미있다
                parts["style"] = 1.0 - abs(sim - 0.45) / 0.55
            note = ps_mod.matchup_note_ko(my_style, other_style)
            if parts["style"] > 0.75:
                reasons.append(note)
        else:
            parts["style"] = 0.5

        # 5) 신선함
        played = _history_count(session, player_id, other.id)
        parts["novelty"] = 1.0 / (1.0 + 0.6 * played)
        if played == 0:
            reasons.append("아직 붙어본 적 없음")
        elif played >= 3:
            reasons.append(f"최근 90일 {played}번 대결")

        total = sum(WEIGHTS[k] * v for k, v in parts.items())
        prof = session.get(StyleProfile, other.id)
        out.append(
            Candidate(
                player_id=other.id, name=other.name, rating=r_other.rating, rd=r_other.rd,
                ntrp=rt.ntrp(r_other.rating), confidence=rt.confidence_label(r_other.rd),
                archetype_ko=prof.archetype_ko if prof else "분석 전",
                total=total, parts=parts, reasons=reasons[:3],
                predicted=rt.predicted_score_line(my_rating, r_other),
                matchup_note=note, distance_km=dist, overlap_hours=overlap,
                played_before=played,
            )
        )

    out = [c for c in out if c.total >= min_score]
    out.sort(key=lambda c: -c.total)
    return out[:limit]


def pair_open_requests(session: Session, min_score: float = 0.55) -> list[dict]:
    """열려 있는 요청들끼리 그리디 매칭. (배치 잡으로 주기 실행)"""
    reqs = session.exec(select(MatchRequest).where(MatchRequest.status == "open")).all()
    by_player = {r.player_id: r for r in reqs}
    scored: list[tuple[float, MatchRequest, MatchRequest, dict]] = []
    seen: set[tuple[int, int]] = set()

    for r in reqs:
        cands = suggest_opponents(
            session, r.player_id, limit=20,
            style_preference=r.style_preference,
            window=(r.window_start, r.window_end),
            max_distance_km=r.max_distance_km,
        )
        for c in cands:
            if c.player_id not in by_player:
                continue
            key = tuple(sorted((r.player_id, c.player_id)))
            if key in seen:
                continue
            seen.add(key)
            other = by_player[c.player_id]
            if _overlap_hours(r.window_start, r.window_end, other.window_start, other.window_end) < 0.5:
                continue
            scored.append((c.total, r, other, c.to_dict()))

    scored.sort(key=lambda s: -s[0])
    used: set[int] = set()
    made: list[dict] = []
    for score, r1, r2, info in scored:
        if score < min_score or r1.player_id in used or r2.player_id in used:
            continue
        used.add(r1.player_id)
        used.add(r2.player_id)
        start = max(_aware(r1.window_start), _aware(r2.window_start))
        for r, partner in ((r1, r2), (r2, r1)):
            r.status = "matched"
            r.matched_with_id = partner.player_id
            session.add(r)
        made.append({
            "playerA": r1.player_id, "playerB": r2.player_id,
            "score": round(score, 4), "startAt": start.isoformat(),
            "court": r1.court or r2.court, "format": r1.format, "detail": info,
        })
    session.commit()
    return made


def ladder(session: Session, limit: int = 50, court: Optional[str] = None) -> list[dict]:
    """전체 랭킹 보드."""
    q = select(Player)
    if court:
        q = q.where(Player.home_court == court)
    players = session.exec(q).all()
    rows = []
    for p in players:
        r = session.get(PlayerRating, p.id)
        prof = session.get(StyleProfile, p.id)
        rating = rt.Rating(r.rating, r.rd, r.vol) if r else rt.Rating()
        rows.append({
            "playerId": p.id, "name": p.name, "homeCourt": p.home_court,
            "rating": round(rating.rating, 1), "rd": round(rating.rd, 1),
            "ntrp": rt.ntrp(rating.rating), "confidence": rt.confidence_label(rating.rd),
            "matches": r.matches if r else 0,
            "wins": r.wins if r else 0, "losses": r.losses if r else 0,
            "archetype": prof.archetype_ko if prof else "분석 전",
            "tags": prof.tags if prof else [],
        })
    rows.sort(key=lambda x: -x["rating"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows[:limit]


__all__ = ["suggest_opponents", "pair_open_requests", "ladder", "Candidate", "haversine_km", "WEIGHTS"]
