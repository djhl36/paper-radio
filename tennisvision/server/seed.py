"""데모 데이터 생성.

    python -m server.seed            # DB 를 비우고 데모 데이터 채우기
    python -m server.seed --keep     # 기존 데이터 유지하고 추가

합성 경기(tools/simulate.py)로 만든 분석 결과가 data/sample_analysis.json 에
있으면 그것도 실제 분석 경기로 함께 적재한다.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, SQLModel, select

from engine.analytics.playstyle import ARCHETYPES, AXES

from .db import engine, init_db
from .ingest import apply_manual_result, store_analysis
from .leagues import create_league, join_league, start_league
from .matching import suggest_opponents
from .models import (
    League,
    Match,
    MatchRequest,
    Player,
    PlayerRating,
    StyleProfile,
)

COURTS = [
    ("잠실종합운동장 테니스장", 37.5150, 127.0730),
    ("올림픽공원 테니스장", 37.5210, 127.1220),
    ("한강난지 테니스장", 37.5680, 126.8770),
    ("양재시민의숲 테니스장", 37.4700, 127.0380),
]

PEOPLE = [
    ("김민수", "right", "aggressive_baseliner", 1720, 0),
    ("이지현", "right", "counterpuncher", 1660, 1),
    ("박준영", "left", "big_server", 1690, 0),
    ("최서연", "right", "all_courter", 1580, 1),
    ("정우성", "right", "serve_and_volley", 1610, 2),
    ("한소희", "left", "crafty", 1540, 2),
    ("오세훈", "right", "grinder", 1495, 3),
    ("윤아름", "right", "aggressive_baseliner", 1470, 0),
    ("장도윤", "right", "counterpuncher", 1440, 1),
    ("서지우", "right", "all_courter", 1400, 3),
    ("문채원", "left", "crafty", 1360, 2),
    ("강태호", "right", "grinder", 1320, 3),
]


def wipe() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def seed(keep: bool = False, seed_value: int = 11) -> dict:
    init_db()
    if not keep:
        wipe()
    rng = random.Random(seed_value)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        players: list[Player] = []
        for name, handed, archetype, rating, court_idx in PEOPLE:
            court, lat, lon = COURTS[court_idx]
            p = Player(
                name=name, handed=handed, backhand=rng.choice(["one", "two"]),
                home_court=court, lat=lat + rng.uniform(-0.01, 0.01),
                lon=lon + rng.uniform(-0.01, 0.01),
                self_level=round(2.5 + (rating - 1300) / 350 * 0.5 * 2) / 2,
                bio=f"{ARCHETYPES[archetype]['ko']} 스타일. 주 3회 {court}에서 칩니다.",
            )
            session.add(p)
            session.commit()
            session.refresh(p)
            players.append(p)

            rd = rng.uniform(45, 130)
            session.add(PlayerRating(
                player_id=p.id, rating=float(rating), rd=rd, vol=0.06,
                matches=rng.randint(6, 40), wins=0, losses=0,
                peak_rating=float(rating) + rng.uniform(0, 40),
                last_match_at=now - timedelta(days=rng.randint(1, 30)),
            ))
            centroid = ARCHETYPES[archetype]["centroid"]
            vector = {a: round(min(98.0, max(4.0, centroid[a] + rng.uniform(-9, 9))), 1) for a in AXES}
            session.add(StyleProfile(
                player_id=p.id, vector=vector, archetype=archetype,
                archetype_ko=ARCHETYPES[archetype]["ko"],
                confidence=round(rng.uniform(0.55, 0.92), 2),
                tags=_tags_for(vector), matches=rng.randint(3, 18),
            ))
        session.commit()

        # 지난 경기 몇 개 (레이팅/전적이 실제로 움직이도록)
        for _ in range(28):
            a, b = rng.sample(players, 2)
            ga, gb = rng.choice([(6, 4), (6, 3), (7, 5), (6, 2), (7, 6), (6, 0)])
            if rng.random() < 0.5:
                ga, gb = gb, ga
            near_won = ga > gb
            m = Match(
                public_id=f"seed{rng.randint(100000, 999999)}", source="upload", status="done",
                near_player_id=a.id, far_player_id=b.id, rated=True,
                court=a.home_court, played_at=now - timedelta(days=rng.randint(2, 120)),
                winner_player_id=a.id if near_won else b.id,
                score_json={"snapshot": {"scoreString": f"{ga}-{gb}", "finished": True}},
            )
            session.add(m)
            session.commit()
            apply_manual_result(session, a.id, b.id, ga, gb, near_won)

        # 매칭 큐
        for p in rng.sample(players, 8):
            start = now + timedelta(days=rng.randint(0, 5), hours=rng.randint(7, 18))
            session.add(MatchRequest(
                player_id=p.id, window_start=start, window_end=start + timedelta(hours=3),
                court=p.home_court, max_distance_km=rng.choice([5, 10, 20]),
                format=rng.choice(["one_set", "best_of_3", "club_single_set_noad"]),
                intent=rng.choice(["competitive", "practice"]),
                style_preference=rng.choice(["balanced", "similar", "contrast"]),
                note=rng.choice(["가볍게 한 세트", "실전처럼 치고 싶어요", "라켓 여분 있습니다", ""]),
            ))
        session.commit()

        # 리그 2개
        rr = create_league(
            session, name="주말 클럽 리그 (풀리그)", kind="round_robin",
            court=COURTS[0][0], max_players=8, starts_at=now + timedelta(days=3),
            description="8인 풀리그. 1세트 노애드. 매주 토요일 오전.",
        )
        for p in players[:8]:
            join_league(session, rr.id, p.id)
        start_league(session, rr.id)

        cup = create_league(
            session, name="가을 오픈 토너먼트", kind="single_elim",
            court=COURTS[1][0], max_players=8, rating_min=1350,
            starts_at=now + timedelta(days=10),
            description="레이팅 1350 이상. 단판 토너먼트, 8강부터.",
        )
        for p in sorted(players, key=lambda x: -x.id)[:8]:
            try:
                join_league(session, cup.id, p.id)
            except ValueError:
                pass
        start_league(session, cup.id)

        ladder = create_league(
            session, name="상시 사다리 리그", kind="ladder", court=COURTS[2][0],
            max_players=16, description="언제든 자기보다 3계단 위까지 도전 가능.",
        )
        for p in players:
            join_league(session, ladder.id, p.id)
        start_league(session, ladder.id)

        # 합성 경기 분석 결과가 있으면 실제 분석 경기로 적재
        ingested = _ingest_sample(session, players)

        summary = {
            "players": len(players),
            "matches": len(session.exec(select(Match)).all()),
            "leagues": len(session.exec(select(League)).all()),
            "requests": len(session.exec(select(MatchRequest)).all()),
            "sampleMatchId": ingested,
        }
        top = suggest_opponents(session, players[0].id, limit=3)
        summary["exampleSuggestions"] = [
            f"{c.name} (점수 {c.total:.2f}) — {c.reasons[0] if c.reasons else ''}" for c in top
        ]
    return summary


def _tags_for(vector: dict) -> list[str]:
    tags = []
    if vector["serve"] >= 70:
        tags.append("서브 강점")
    if vector["consistency"] >= 70:
        tags.append("에러 적음")
    if vector["net_play"] >= 70:
        tags.append("네트 지향")
    if vector["movement"] >= 70:
        tags.append("수비 범위 넓음")
    if vector["aggression"] >= 70:
        tags.append("선제 공격")
    return tags


def _ingest_sample(session: Session, players: list[Player]) -> int | None:
    path = Path("data/sample_analysis.json")
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    analysis = _analysis_from_dict(raw)
    if analysis is None:
        return None
    m = Match(
        public_id=raw.get("match_id", "sample"), source="upload", status="done",
        near_player_id=players[0].id, far_player_id=players[1].id,
        format="best_of_3", court=players[0].home_court,
        video_path=str(Path("data/sample_match.webm").resolve()),
        analysis_path=str(path.resolve()),
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    store_analysis(session, m, analysis)
    return m.id


def _analysis_from_dict(raw: dict):
    """저장된 JSON 을 MatchAnalysis 로 되살린다."""
    from engine.schema import (
        Calibration,
        HighlightClip,
        LineCall,
        MatchAnalysis,
        PointRecord,
        Shot,
    )

    def mk(cls, d: dict):
        fields = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in fields})

    try:
        points = []
        for p in raw.get("points", []):
            pr = mk(PointRecord, {**p, "shots": [], "calls": []})
            pr.shots = [mk(Shot, s) for s in p.get("shots", [])]
            pr.calls = [mk(LineCall, c) for c in p.get("calls", [])]
            points.append(pr)
        return MatchAnalysis(
            match_id=raw.get("match_id", "sample"),
            fps=raw.get("fps", 30.0), duration=raw.get("duration", 0.0),
            calibration=mk(Calibration, raw["calibration"]) if raw.get("calibration") else None,
            points=points,
            shots=[mk(Shot, s) for s in raw.get("shots", [])],
            calls=[mk(LineCall, c) for c in raw.get("calls", [])],
            highlights=[mk(HighlightClip, h) for h in raw.get("highlights", [])],
            final_score=raw.get("final_score", {}),
            player_names=raw.get("player_names", {}),
            stats=raw.get("stats", {}), reports=raw.get("reports", {}),
            styles=raw.get("styles", {}), quality=raw.get("quality", {}),
        )
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="기존 데이터 유지")
    args = ap.parse_args()
    summary = seed(keep=args.keep)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
