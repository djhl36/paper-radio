"""레이팅(Glicko-2), 플레이스타일, 매칭, 리그 로직 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.ratings as rt  # noqa: E402
from engine.analytics.playstyle import (  # noqa: E402
    ARCHETYPES,
    AXES,
    archetype_of_vector,
    blend,
    style_contrast,
    style_similarity,
)
from engine.analytics.report import PlayerStats, build_report  # noqa: E402


# ---------- Glicko-2 ----------
def test_new_player_has_wide_uncertainty():
    r = rt.Rating()
    lo, hi = r.interval95()
    assert hi - lo > 1000
    assert rt.confidence_label(r.rd) == "신규"


def test_beating_stronger_opponent_raises_rating_more():
    me = rt.Rating(1500, 100, 0.06)
    weak = rt.Rating(1300, 60, 0.06)
    strong = rt.Rating(1800, 60, 0.06)
    gain_weak = rt.update(me, [(weak, 1.0)]).rating - me.rating
    gain_strong = rt.update(me, [(strong, 1.0)]).rating - me.rating
    assert gain_strong > gain_weak > 0


def test_rd_shrinks_with_games():
    r = rt.Rating(1500, 200, 0.06)
    opp = rt.Rating(1500, 60, 0.06)
    after = rt.update(r, [(opp, 1.0)])
    assert after.rd < r.rd


def test_inactivity_increases_rd():
    r = rt.Rating(1500, 60, 0.06)
    after = rt.decay(r, periods=20)
    assert after.rd > r.rd
    assert after.rating == r.rating


def test_margin_of_victory_matters():
    a = rt.Rating(1500, 80, 0.06)
    b = rt.Rating(1500, 80, 0.06)
    crush, _ = rt.update_pair(a.copy(), b.copy(), 6, 0, True)
    tight, _ = rt.update_pair(a.copy(), b.copy(), 7, 6, True)
    assert crush.rating > tight.rating


def test_expected_score_symmetry():
    a = rt.Rating(1600, 60, 0.06)
    b = rt.Rating(1400, 60, 0.06)
    assert abs(rt.expected_score(a, b) + rt.expected_score(b, a) - 1.0) < 1e-9
    assert rt.expected_score(a, b) > 0.7


def test_competitiveness_peaks_for_equal_players():
    equal = rt.competitiveness(rt.Rating(1500, 60), rt.Rating(1500, 60))
    lopsided = rt.competitiveness(rt.Rating(1900, 60), rt.Rating(1300, 60))
    assert equal > 0.99 and lopsided < 0.4


def test_ntrp_mapping_monotone():
    assert rt.ntrp(1150) < rt.ntrp(1500) < rt.ntrp(1900)
    assert rt.ntrp(1500) == 3.5


# ---------- 플레이스타일 ----------
def test_archetype_recovered_from_its_own_centroid():
    for key, spec in ARCHETYPES.items():
        got, _ko, _scores = archetype_of_vector(spec["centroid"])
        assert got == key, f"{key} 센트로이드가 {got} 로 분류됨"


def test_similarity_bounds():
    a = ARCHETYPES["big_server"]["centroid"]
    b = ARCHETYPES["grinder"]["centroid"]
    assert style_similarity(a, a) > 0.99
    assert style_similarity(a, b) < 0.5
    assert abs(style_similarity(a, b) + style_contrast(a, b) - 1.0) < 1e-6


def test_blend_moves_toward_new_style():
    from engine.analytics.playstyle import PlayStyle

    prev = {a: 50.0 for a in AXES}
    new = PlayStyle(side="near", vector={a: 90.0 for a in AXES}, confidence=1.0)
    after = blend(prev, new, alpha=0.5)
    assert 50 < after["serve"] < 90


# ---------- 코칭 리포트 ----------
def test_report_needs_minimum_samples():
    stats = PlayerStats(side="near", metrics={"first_serve_in_pct": 0.95}, samples={"first_serve_in_pct": 2})
    report = build_report(stats)
    assert not report.strengths, "표본이 적은 지표는 강점으로 뽑히면 안 된다"


def test_report_picks_extremes():
    stats = PlayerStats(
        side="near",
        metrics={
            "first_serve_in_pct": 0.80,        # 아주 높음 -> 강점
            "double_fault_rate": 0.20,          # 아주 높음(나쁨) -> 약점
            "return_won_pct": 0.38,             # 평균
        },
        samples={"first_serve_in_pct": 40, "double_fault_rate": 40, "return_won_pct": 40},
        counts={"winners": 10, "unforcedErrors": 8},
    )
    report = build_report(stats)
    assert report.strengths and report.strengths[0].key == "first_serve_in_pct"
    assert report.weaknesses and report.weaknesses[0].key == "double_fault_rate"
    assert report.drills, "약점에는 드릴 추천이 붙어야 한다"


# ---------- 리그 대진 ----------
def test_round_robin_pairs_everyone_once():
    from server.leagues import _round_robin

    class E:
        def __init__(self, pid):
            self.player_id = pid

    entries = [E(i) for i in range(1, 7)]
    fixtures = _round_robin(entries)
    pairs = {frozenset((a, b)) for _, _, a, b in fixtures if a and b}
    assert len(pairs) == 15, "6명 풀리그는 15경기"
    rounds = {r for r, _, _, _ in fixtures}
    assert len(rounds) == 5


def test_round_robin_handles_odd_count():
    from server.leagues import _round_robin

    class E:
        def __init__(self, pid):
            self.player_id = pid

    entries = [E(i) for i in range(1, 6)]
    fixtures = _round_robin(entries)
    real = [(a, b) for _, _, a, b in fixtures if a and b]
    assert len(real) == 10, "5명이면 10경기 + 부전승"


def test_single_elim_seeds_top_and_bottom():
    from server.leagues import _single_elim

    class E:
        def __init__(self, pid):
            self.player_id = pid

    entries = [E(i) for i in range(1, 9)]     # 이미 레이팅 내림차순이라고 가정
    fixtures = _single_elim(entries)
    first = [(a, b) for r, _, a, b in fixtures if r == 1]
    assert (1, 8) in first or (8, 1) in first, "1시드는 8시드와 붙어야 한다"
    assert len(fixtures) == 7, "8강 토너먼트는 총 7경기"
