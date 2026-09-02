"""테니스 점수 규칙 테스트.

규칙 엔진은 비전이 아무리 좋아져도 틀리면 안 되는 부분이라 촘촘히 검증한다.
    python -m pytest tests/ -q     (pytest 없으면 python tests/run_all.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.umpire.scoring import MatchFormat, ScoreBoard, start_match  # noqa: E402


def win_game(sb: ScoreBoard, player: str) -> dict:
    res = {}
    while True:
        res = sb.award_point(player)
        if res["game_won"] or res["set_won"] or res["match_won"] or sb.finished:
            return res


def test_basic_points():
    sb = start_match("best_of_3")
    assert sb.point_display() == ("0", "0")
    sb.award_point("A")
    assert sb.point_display() == ("15", "0")
    sb.award_point("A")
    sb.award_point("B")
    assert sb.point_display() == ("30", "15")


def test_deuce_and_advantage():
    sb = start_match("best_of_3")
    for _ in range(3):
        sb.award_point("A")
        sb.award_point("B")
    assert sb.point_display() == ("40", "40")
    assert sb.announce_ko() == "듀스"
    sb.award_point("A")
    assert sb.point_display() == ("AD", "-")
    sb.award_point("B")
    assert sb.point_display() == ("40", "40")
    sb.award_point("B")
    res = sb.award_point("B")
    assert res["game_won"] and sb.current_set.games["B"] == 1


def test_no_ad_sudden_death():
    sb = ScoreBoard(MatchFormat(ad_scoring=False))
    for _ in range(3):
        sb.award_point("A")
        sb.award_point("B")
    res = sb.award_point("A")
    assert res["game_won"], "노애드에서는 40-40 다음 한 점으로 게임이 끝나야 한다"


def test_serve_alternates_each_game():
    sb = start_match("best_of_3")
    assert sb.server == "A"
    win_game(sb, "A")
    assert sb.server == "B"
    win_game(sb, "B")
    assert sb.server == "A"


def test_changeover_after_odd_games():
    sb = start_match("best_of_3")
    ends0 = dict(sb.ends)
    res = win_game(sb, "A")            # 1게임 후 -> 코트 교체
    assert res["changeover"]
    assert sb.ends != ends0
    res = win_game(sb, "B")            # 2게임 후 -> 교체 없음
    assert not res["changeover"]


def test_set_requires_two_game_lead():
    sb = start_match("best_of_3")
    for _ in range(5):
        win_game(sb, "A")
        win_game(sb, "B")
    assert sb.current_set.games == {"A": 5, "B": 5}
    res = win_game(sb, "A")
    assert not res["set_won"], "6-5 로는 세트가 끝나지 않는다"
    res = win_game(sb, "A")
    assert res["set_won"] and sb.sets_won["A"] == 1


def test_tiebreak_starts_at_6_6_and_serve_rotation():
    sb = ScoreBoard(MatchFormat(sets_to_win=1))
    for _ in range(6):
        win_game(sb, "A")
        win_game(sb, "B")
    assert sb.in_tiebreak
    first = sb.server
    sb.award_point("A")                       # 1점 뒤 교대
    assert sb.server != first
    second = sb.server
    sb.award_point("A")
    assert sb.server == second                # 2점씩
    sb.award_point("A")
    assert sb.server == first


def test_tiebreak_changeover_every_six_points():
    sb = ScoreBoard(MatchFormat(sets_to_win=1))
    for _ in range(6):
        win_game(sb, "A")
        win_game(sb, "B")
    changes = []
    for i in range(6):
        res = sb.award_point("A" if i % 2 == 0 else "B")
        changes.append(res["changeover"])
    assert changes == [False, False, False, False, False, True]


def test_tiebreak_needs_two_point_lead():
    sb = ScoreBoard(MatchFormat(sets_to_win=1))
    for _ in range(6):
        win_game(sb, "A")
        win_game(sb, "B")
    for _ in range(6):
        sb.award_point("A")
        sb.award_point("B")
    assert sb.points == {"A": 6, "B": 6}
    sb.award_point("A")
    assert not sb.finished, "7-6 으로는 타이브레이크가 끝나지 않는다"
    sb.award_point("A")
    assert sb.finished and sb.winner == "A"


def test_next_set_server_after_tiebreak():
    sb = ScoreBoard(MatchFormat(sets_to_win=2))
    for _ in range(6):
        win_game(sb, "A")
        win_game(sb, "B")
    tb_first = sb.server
    for _ in range(7):
        sb.award_point("A")
    assert sb.sets_won["A"] == 1
    assert sb.server != tb_first, "타이브레이크 첫 서버의 상대가 다음 세트 첫 서버"


def test_match_tiebreak_format():
    sb = ScoreBoard(MatchFormat.preset("fast4"))
    # fast4: 4게임 세트, 3-3 타이브레이크, 최종 세트는 10점 매치 타이브레이크
    for _ in range(4):
        win_game(sb, "A")
    assert sb.sets_won["A"] == 1
    for _ in range(4):
        win_game(sb, "B")
    assert sb.sets_won["B"] == 1
    assert sb.in_tiebreak, "1-1 이 되면 곧바로 매치 타이브레이크가 시작돼야 한다"
    assert sb.tiebreak_target() == 10
    for _ in range(10):
        sb.award_point("A")
    assert sb.finished and sb.winner == "A"


def test_double_fault_awards_point_to_receiver():
    sb = start_match("best_of_3")
    r1 = sb.fault()
    assert not r1["double_fault"] and sb.serve_number == 2
    r2 = sb.fault()
    assert r2["double_fault"]
    assert sb.points["B"] == 1 and sb.serve_number == 1


def test_court_side_alternates():
    sb = start_match("best_of_3")
    assert sb.court_side() == "deuce"
    sb.award_point("A")
    assert sb.court_side() == "ad"
    sb.award_point("B")
    assert sb.court_side() == "deuce"


def test_pressure_flags():
    sb = start_match("best_of_3")
    for _ in range(3):
        sb.award_point("B")           # 0-40, B 가 리시버 -> 브레이크 포인트
    p = sb.pressure()
    assert p["breakPoint"] == "B" and p["gamePoint"] == "B"
    assert p["setPoint"] is None


def test_match_point_detection():
    sb = ScoreBoard(MatchFormat(sets_to_win=1))
    for _ in range(5):
        win_game(sb, "A")
    for _ in range(3):
        sb.award_point("A")
    assert sb.pressure()["matchPoint"] == "A"


def test_undo_by_replay():
    """로그를 되감아 상태를 복원할 수 있어야 한다(라이브 되돌리기가 이걸 쓴다)."""
    sb = start_match("best_of_3")
    for w in ["A", "B", "A", "A", "B", "A"]:
        sb.award_point(w)
    before = sb.score_string()
    sb.award_point("B")
    replay = start_match("best_of_3")
    for entry in sb.log[:-1]:
        replay.award_point(entry["winner"])
    assert replay.score_string() == before


def test_ends_swap_consistency():
    """코트 교체가 일어나도 player_at/side_of 가 서로 역함수여야 한다."""
    sb = start_match("best_of_3")
    for _ in range(7):
        win_game(sb, "A")
        for side in ("near", "far"):
            p = sb.player_at(side)
            assert sb.side_of(p) == side
