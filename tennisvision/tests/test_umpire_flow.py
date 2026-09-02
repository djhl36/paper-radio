"""심판 상태 머신: 이벤트 시퀀스 -> 포인트/점수.

비전 없이 이벤트를 직접 만들어 넣어서, 규칙 로직만 독립적으로 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.geometry import HALF_LENGTH  # noqa: E402
from engine.schema import BallEvent, BallTrack  # noqa: E402
from engine.umpire.rally import Umpire, UmpireConfig  # noqa: E402
from engine.umpire.scoring import ScoreBoard, MatchFormat  # noqa: E402
from engine.vision.court import calibrate_manual  # noqa: E402

CORNERS = ["near_left_doubles", "near_right_doubles", "far_right_doubles", "far_left_doubles"]
IMAGE_PTS = [[182.4, 682.7], [1066.8, 694.6], [780.7, 275.8], [510.4, 274.7]]


def make_env(fmt: str = "best_of_3"):
    calib = calibrate_manual(IMAGE_PTS, CORNERS, frame_size=(1280, 720))
    track = BallTrack(positions=[(640.0, 400.0)] * 4000, confidence=[1.0] * 4000, fps=30.0)
    board = ScoreBoard(MatchFormat.preset(fmt), first_server="A", first_server_side="near")
    ump = Umpire(board, calib, track, UmpireConfig())
    return board, ump


class Clock:
    def __init__(self):
        self.t = 0.0

    def step(self, dt=0.7):
        self.t += dt
        return self.t


def hit(clock, side, dt=0.7, x=0.0, y=0.0):
    t = clock.step(dt)
    return BallEvent(kind="hit", frame=int(t * 30), t=t, image_xy=(640, 400),
                     court_xy=(x, y), confidence=0.9, by_side=side)


def bounce(clock, x, y, dt=0.6):
    t = clock.step(dt)
    return BallEvent(kind="bounce", frame=int(t * 30), t=t, image_xy=(640, 400),
                     court_xy=(x, y), confidence=0.9)


def serve_in(board, clock, dt=0.6):
    """현재 스코어보드가 요구하는 서비스 박스 한가운데로 떨어지는 바운스."""
    from engine.geometry import serve_target_box

    box = serve_target_box(board.ends[board.server], board.court_side())
    x = (box.x_min + box.x_max) / 2
    y = (box.y_min + box.y_max) / 2
    return bounce(clock, x, y, dt)


def serve_long(board, clock, dt=0.6):
    """서비스 박스를 넘겨 떨어지는(=폴트) 바운스."""
    from engine.geometry import serve_target_box

    box = serve_target_box(board.ends[board.server], board.court_side())
    x = (box.x_min + box.x_max) / 2
    y = (box.y_max + 1.5) if box.y_max > 0 else (box.y_min - 1.5)
    return bounce(clock, x, y, dt)


def test_ace_scores_for_server():
    board, ump = make_env()
    c = Clock()
    evs = [
        hit(c, "near", 2.0, x=2.0, y=-HALF_LENGTH),
        serve_in(board, c),                          # 서브 인 (파 듀스 박스)
        bounce(c, -3.0, HALF_LENGTH - 1.0),          # 두 번째 바운스 = 에이스
    ]
    ump.process_all(evs)
    assert len(ump.points) == 1
    pt = ump.points[0]
    assert pt.winner_side == "near"
    assert pt.end_reason == "ace"
    assert board.points["A"] == 1


def test_serve_fault_then_second_serve_in():
    board, ump = make_env()
    c = Clock()
    evs = [
        hit(c, "near", 2.0),
        serve_long(board, c),                         # 폴트 (박스 밖)
        hit(c, "near", 3.0),                          # 세컨 서브
        serve_in(board, c),                           # 인
        hit(c, "far", 0.5, x=-2.0, y=HALF_LENGTH - 1),
        bounce(c, 0.0, -6.0),
        bounce(c, 0.5, -8.0),                         # 니어가 못 받음 -> 파 득점
    ]
    ump.process_all(evs)
    assert len(ump.points) == 1
    assert ump.points[0].winner_side == "far"
    assert ump.points[0].serve_number == 2
    faults = [c for c in ump.calls if c.kind == "fault"]
    assert len(faults) == 1


def test_double_fault():
    board, ump = make_env()
    c = Clock()
    evs = [
        hit(c, "near", 2.0),
        serve_long(board, c),
        hit(c, "near", 3.0),
        serve_long(board, c),
    ]
    ump.process_all(evs)
    assert len(ump.points) == 1
    assert ump.points[0].end_reason == "double_fault"
    assert ump.points[0].winner_side == "far"
    assert board.points["B"] == 1


def test_rally_out_gives_point_to_opponent():
    board, ump = make_env()
    c = Clock()
    evs = [
        hit(c, "near", 2.0),
        serve_in(board, c),
        hit(c, "far", 0.5, x=-2.0, y=HALF_LENGTH - 1),
        bounce(c, 0.0, -7.0),
        hit(c, "near", 0.5, x=0.0, y=-8.0),
        bounce(c, 0.0, HALF_LENGTH + 0.8),            # 니어가 아웃
    ]
    ump.process_all(evs)
    assert ump.points[0].end_reason == "out"
    assert ump.points[0].winner_side == "far"


def test_ball_into_net_gives_point_to_opponent():
    board, ump = make_env()
    c = Clock()
    evs = [
        hit(c, "near", 2.0),
        serve_in(board, c),
        hit(c, "far", 0.5, x=-2.0, y=HALF_LENGTH - 1),
        bounce(c, 0.0, -7.0),
        hit(c, "near", 0.5, x=0.0, y=-8.0),
        bounce(c, 0.0, -1.5),                         # 자기 진영에 떨어짐 = 네트
    ]
    ump.process_all(evs)
    assert ump.points[0].end_reason == "net"
    assert ump.points[0].winner_side == "far"


def test_rally_length_counts_hits():
    board, ump = make_env()
    c = Clock()
    evs = [hit(c, "near", 2.0), serve_in(board, c)]
    side = "far"
    for i in range(4):
        evs.append(hit(c, side, 0.5))
        evs.append(bounce(c, 0.0, 7.0 if side == "near" else -7.0))
        side = "near" if side == "far" else "far"
    evs.append(hit(c, side, 0.5))
    evs.append(bounce(c, 0.0, HALF_LENGTH + 1.0 if side == "near" else -HALF_LENGTH - 1.0))
    ump.process_all(evs)
    assert len(ump.points) == 1
    assert ump.points[0].rally_length == 6


def test_two_points_are_separated_by_gap():
    board, ump = make_env()
    c = Clock()
    for _ in range(2):
        ump.process_all([
            hit(c, "near", 3.0),
            serve_in(board, c),
            bounce(c, -3.0, HALF_LENGTH - 1.0),
        ])
    assert len(ump.points) == 2
    assert board.points["A"] == 2


def test_score_string_progresses():
    board, ump = make_env()
    c = Clock()
    for _ in range(4):
        ump.process_all([
            hit(c, "near", 3.0),
            serve_in(board, c),
            bounce(c, -3.0, HALF_LENGTH - 1.0),
        ])
    assert board.current_set.games["A"] == 1, board.score_string()
