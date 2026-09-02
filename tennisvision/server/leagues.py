"""리그 / 토너먼트.

세 가지 형식을 지원한다.
  round_robin : 풀리그. 참가자가 짝수/홀수 모두 되게 서클 알고리즘으로 라운드 생성.
  single_elim : 단판 토너먼트. 레이팅으로 시딩하고 부전승은 상위 시드에.
  ladder      : 사다리. 도전은 자기보다 몇 계단 위까지만 가능, 이기면 자리 교환.

경기 결과는 Fixture 에 기록되고, 영상 분석을 붙이면 Match 와 연결된다.
어느 쪽이든 Glicko-2 레이팅에 반영되므로 리그 성적이 곧 매칭 품질로 이어진다.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlmodel import Session, select

from . import ratings as rt
from .ingest import apply_manual_result
from .models import Fixture, League, LeagueEntry, Player, PlayerRating

LADDER_CHALLENGE_RANGE = 3     # 자기보다 최대 3계단 위까지 도전 가능


def create_league(session: Session, **kw) -> League:
    league = League(**kw)
    session.add(league)
    session.commit()
    session.refresh(league)
    return league


def join_league(session: Session, league_id: int, player_id: int) -> LeagueEntry:
    league = session.get(League, league_id)
    if league is None:
        raise ValueError("리그를 찾을 수 없습니다")
    if league.status != "open":
        raise ValueError("이미 시작된 리그입니다")
    existing = session.exec(
        select(LeagueEntry).where(
            LeagueEntry.league_id == league_id, LeagueEntry.player_id == player_id
        )
    ).first()
    if existing:
        return existing
    count = len(session.exec(select(LeagueEntry).where(LeagueEntry.league_id == league_id)).all())
    if count >= league.max_players:
        raise ValueError("정원이 찼습니다")
    r = session.get(PlayerRating, player_id)
    rating = r.rating if r else rt.DEFAULT_RATING
    if league.rating_min is not None and rating < league.rating_min:
        raise ValueError(f"이 리그는 레이팅 {league.rating_min:.0f} 이상만 참가할 수 있습니다")
    if league.rating_max is not None and rating > league.rating_max:
        raise ValueError(f"이 리그는 레이팅 {league.rating_max:.0f} 이하만 참가할 수 있습니다")
    entry = LeagueEntry(league_id=league_id, player_id=player_id)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _seeded_entries(session: Session, league_id: int) -> list[LeagueEntry]:
    entries = session.exec(select(LeagueEntry).where(LeagueEntry.league_id == league_id)).all()
    def rating_of(e: LeagueEntry) -> float:
        r = session.get(PlayerRating, e.player_id)
        return r.rating if r else rt.DEFAULT_RATING
    entries.sort(key=lambda e: -rating_of(e))
    for i, e in enumerate(entries, 1):
        e.seed = i
        session.add(e)
    session.commit()
    return entries


def start_league(session: Session, league_id: int, first_round_at: Optional[datetime] = None,
                 days_between_rounds: int = 7) -> list[Fixture]:
    league = session.get(League, league_id)
    if league is None:
        raise ValueError("리그를 찾을 수 없습니다")
    entries = _seeded_entries(session, league_id)
    if len(entries) < 2:
        raise ValueError("참가자가 2명 이상이어야 시작할 수 있습니다")

    start = first_round_at or league.starts_at or datetime.now(timezone.utc) + timedelta(days=1)
    if league.kind == "round_robin":
        fixtures = _round_robin(entries)
    elif league.kind == "single_elim":
        fixtures = _single_elim(entries)
    elif league.kind == "ladder":
        fixtures = []          # 사다리는 도전 방식이라 미리 대진을 만들지 않는다
    else:
        raise ValueError(f"알 수 없는 리그 형식: {league.kind}")

    rows: list[Fixture] = []
    for rnd, slot, p1, p2 in fixtures:
        rows.append(
            Fixture(
                league_id=league_id, round=rnd, slot=slot,
                player1_id=p1, player2_id=p2, court=league.court,
                scheduled_at=start + timedelta(days=days_between_rounds * (rnd - 1)),
                status="scheduled" if (p1 and p2) else "walkover",
                winner_id=(p1 or p2) if not (p1 and p2) else None,
            )
        )
    session.add_all(rows)
    league.status = "running"
    session.add(league)
    session.commit()
    for r in rows:
        session.refresh(r)
    return rows


def _round_robin(entries: Sequence[LeagueEntry]) -> list[tuple[int, int, Optional[int], Optional[int]]]:
    """서클 방식 풀리그. 홀수면 부전승(None) 자리를 넣는다."""
    ids: list[Optional[int]] = [e.player_id for e in entries]
    if len(ids) % 2:
        ids.append(None)
    n = len(ids)
    fixtures = []
    arr = list(ids)
    for rnd in range(1, n):
        for slot in range(n // 2):
            a, b = arr[slot], arr[n - 1 - slot]
            if a is None and b is None:
                continue
            # 라운드마다 홈/어웨이를 번갈아 (서브권 균형)
            if rnd % 2 == 0:
                a, b = b, a
            fixtures.append((rnd, slot, a, b))
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]      # 첫 자리 고정 회전
    return fixtures


def _single_elim(entries: Sequence[LeagueEntry]) -> list[tuple[int, int, Optional[int], Optional[int]]]:
    """시드 기반 단판 토너먼트 1라운드 대진(1 vs N, 2 vs N-1 ...) + 빈 상위 라운드."""
    n = len(entries)
    size = 1 << math.ceil(math.log2(max(n, 2)))
    seeds: list[Optional[int]] = [e.player_id for e in entries] + [None] * (size - n)
    order = _seed_order(size)
    fixtures = []
    for slot in range(size // 2):
        a = seeds[order[2 * slot] - 1]
        b = seeds[order[2 * slot + 1] - 1]
        fixtures.append((1, slot, a, b))
    rounds = int(math.log2(size))
    for rnd in range(2, rounds + 1):
        for slot in range(size >> rnd):
            fixtures.append((rnd, slot, None, None))
    return fixtures


def _seed_order(size: int) -> list[int]:
    """표준 토너먼트 시드 배치 (1이 8강 반대편에서 2를 만나도록)."""
    order = [1, 2]
    while len(order) < size:
        m = len(order) * 2 + 1
        nxt = []
        for s in order:
            nxt.append(s)
            nxt.append(m - s)
        order = nxt
    return order


def record_result(
    session: Session, fixture_id: int, winner_id: int,
    winner_games: int, loser_games: int, match_id: Optional[int] = None,
) -> Fixture:
    """대진 결과 기록 -> 순위표 갱신 -> 레이팅 반영 -> 다음 라운드 진출."""
    fx = session.get(Fixture, fixture_id)
    if fx is None:
        raise ValueError("대진을 찾을 수 없습니다")
    if fx.status == "played":
        raise ValueError("이미 결과가 입력된 경기입니다")
    if winner_id not in (fx.player1_id, fx.player2_id):
        raise ValueError("이 대진의 선수가 아닙니다")
    loser_id = fx.player2_id if winner_id == fx.player1_id else fx.player1_id

    fx.status = "played"
    fx.winner_id = winner_id
    fx.match_id = match_id
    fx.score_summary = f"{winner_games}-{loser_games}"
    session.add(fx)

    for pid, won, gf, ga in (
        (winner_id, True, winner_games, loser_games),
        (loser_id, False, loser_games, winner_games),
    ):
        if pid is None:
            continue
        entry = session.exec(
            select(LeagueEntry).where(
                LeagueEntry.league_id == fx.league_id, LeagueEntry.player_id == pid
            )
        ).first()
        if entry is None:
            continue
        entry.wins += 1 if won else 0
        entry.losses += 0 if won else 1
        entry.points += 3 if won else (1 if ga > 0 else 0)
        entry.games_won += gf
        entry.games_lost += ga
        session.add(entry)

    if loser_id is not None and not match_id:
        # 영상 분석이 있으면 ingest 가 이미 레이팅을 반영했으므로 중복하지 않는다
        apply_manual_result(session, winner_id, loser_id, winner_games, loser_games, True)

    _advance_bracket(session, fx)
    session.commit()
    session.refresh(fx)
    return fx


def _advance_bracket(session: Session, fx: Fixture) -> None:
    league = session.get(League, fx.league_id)
    if league is None or league.kind != "single_elim":
        return
    nxt = session.exec(
        select(Fixture).where(
            Fixture.league_id == fx.league_id,
            Fixture.round == fx.round + 1,
            Fixture.slot == fx.slot // 2,
        )
    ).first()
    if nxt is None:
        league.status = "finished"
        session.add(league)
        return
    if fx.slot % 2 == 0:
        nxt.player1_id = fx.winner_id
    else:
        nxt.player2_id = fx.winner_id
    session.add(nxt)


def standings(session: Session, league_id: int) -> list[dict]:
    entries = session.exec(select(LeagueEntry).where(LeagueEntry.league_id == league_id)).all()
    rows = []
    for e in entries:
        p = session.get(Player, e.player_id)
        r = session.get(PlayerRating, e.player_id)
        rows.append({
            "playerId": e.player_id, "name": p.name if p else "?",
            "seed": e.seed, "points": e.points, "wins": e.wins, "losses": e.losses,
            "gamesWon": e.games_won, "gamesLost": e.games_lost,
            "gameDiff": e.games_won - e.games_lost,
            "rating": round(r.rating, 1) if r else rt.DEFAULT_RATING,
        })
    # 승점 -> 게임 득실 -> 승수 -> 레이팅. 경기 전이면 레이팅(=시드) 순서가 된다.
    rows.sort(key=lambda x: (-x["points"], -x["gameDiff"], -x["wins"], -x["rating"]))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def ladder_challenges(session: Session, league_id: int, player_id: int) -> list[dict]:
    """사다리 리그에서 이 선수가 도전할 수 있는 상대."""
    board = standings(session, league_id)
    me = next((i for i, r in enumerate(board) if r["playerId"] == player_id), None)
    if me is None:
        return []
    lo = max(0, me - LADDER_CHALLENGE_RANGE)
    return [
        {**r, "positionsAbove": me - i}
        for i, r in enumerate(board[lo:me], start=lo)
    ]


def bracket(session: Session, league_id: int) -> dict:
    fixtures = session.exec(select(Fixture).where(Fixture.league_id == league_id)).all()
    names = {p.id: p.name for p in session.exec(select(Player)).all()}
    rounds: dict[int, list] = {}
    for f in sorted(fixtures, key=lambda f: (f.round, f.slot)):
        rounds.setdefault(f.round, []).append({
            "id": f.id, "slot": f.slot, "status": f.status,
            "player1": {"id": f.player1_id, "name": names.get(f.player1_id)},
            "player2": {"id": f.player2_id, "name": names.get(f.player2_id)},
            "winnerId": f.winner_id, "score": f.score_summary,
            "scheduledAt": f.scheduled_at.isoformat() if f.scheduled_at else None,
            "court": f.court, "matchId": f.match_id,
        })
    league = session.get(League, league_id)
    return {
        "league": {
            "id": league_id, "name": league.name if league else "",
            "kind": league.kind if league else "", "status": league.status if league else "",
        },
        "rounds": [{"round": r, "fixtures": v} for r, v in sorted(rounds.items())],
    }


__all__ = [
    "create_league", "join_league", "start_league", "record_result",
    "standings", "bracket", "ladder_challenges",
]
