"""샷 단위 분석 — 이벤트/포인트를 Shot 레코드로 바꾼다.

측정값의 정직한 범위
  speed_kmh  : 타격 지점 -> 바운스 지점의 **지면 투영 평균 속도**다. 3D 궤적
               길이와 공중 체류를 무시하므로 실제 라켓 속도보다 낮게 나온다.
               절대값보다 같은 영상 안에서의 상대 비교에 쓰는 것이 맞다.
  depth/lateral : 바운스 순간에만 지면 호모그래피가 정확하므로 이 둘은 신뢰도가 높다.
  spin       : 단안 카메라로는 직접 측정 불가. 바운스 전후 속도비/궤적 형태에서
               나온 `spin_hint` 만 제공하고 라벨은 보수적으로 붙인다.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from ..geometry import (
    SERVICE_LINE_Y,
    SINGLES_HALF_W,
    deuce_x_sign,
    serve_zone,
)
from ..schema import BallEvent, PlayerTrack, PointRecord, Shot, ShotType, Side
from ..umpire.rally import opposite

Handedness = dict  # {"near": "right"|"left", "far": ...}

NET_APPROACH_Y = SERVICE_LINE_Y + 0.5      # 이 안쪽에서 치면 네트 플레이로 본다
DROP_DEPTH_M = 3.2                          # 네트에서 이 안쪽에 떨어지면 드롭샷 후보
LOB_FLIGHT_S = 1.15                         # 체공 시간이 이보다 길면 로브 후보


def _wing(
    ball_x: float, player_x: Optional[float], side: Side, handed: str
) -> ShotType:
    """포핸드/백핸드. 플레이어 위치를 못 잡았으면 코트 절반으로 근사한다."""
    px = player_x if player_x is not None else 0.0
    right_sign = deuce_x_sign(side)                 # 그 선수의 '오른쪽'이 놓인 x 부호
    hand_sign = right_sign if handed == "right" else -right_sign
    return "forehand" if (ball_x - px) * hand_sign > 0 else "backhand"


def _direction(contact_x: Optional[float], bounce_x: float) -> str:
    if contact_x is None:
        return "middle"
    if abs(bounce_x) < 1.2:
        return "middle"
    if contact_x * bounce_x < 0:
        return "cross"           # 코트 반대편 절반으로 보냈다
    return "down_the_line"


def build_shots(
    points: Sequence[PointRecord],
    point_events: Sequence[list[BallEvent]],
    players: Optional[dict[Side, PlayerTrack]] = None,
    handedness: Optional[Handedness] = None,
    fps: float = 30.0,
) -> list[Shot]:
    """포인트별 이벤트를 훑어 Shot 목록을 만들고 각 PointRecord 에도 붙인다."""
    handedness = {"near": "right", "far": "right", **(handedness or {})}
    shots: list[Shot] = []
    global_idx = 0

    for pt, events in zip(points, point_events):
        hits = [e for e in events if e.kind == "hit"]
        pt_shots: list[Shot] = []
        for k, hit in enumerate(hits):
            nxt_bounce = _next_of(events, hit, ("bounce", "net"))
            prev_bounce = _prev_of(events, hit, ("bounce",))
            side: Side = hit.by_side or (pt.server_side if k == 0 else opposite(hits[k - 1].by_side or pt.server_side))
            contact = hit.court_xy
            bounce = nxt_bounce.court_xy if nxt_bounce else None
            player_x = None
            if players and side in players:
                cp = players[side].court_at(hit.frame)
                player_x = cp[0] if cp else None

            flight_s = ((nxt_bounce.frame - hit.frame) / fps) if nxt_bounce else None
            # 직전 샷 이후 바운스 없이 쳤으면 발리
            prev_hit_frame = hits[k - 1].frame if k > 0 else -1
            volleyed = prev_bounce is None or prev_bounce.frame < prev_hit_frame
            near_net = contact is not None and abs(contact[1]) < NET_APPROACH_Y

            shot_type = _classify(
                k=k, side=side, contact=contact, bounce=bounce, player_x=player_x,
                handed=handedness[side], volleyed=volleyed, near_net=near_net,
                flight_s=flight_s, prev_flight=_prev_flight(events, hits, k, fps),
            )

            depth = abs(bounce[1]) if bounce else None
            shot = Shot(
                index=global_idx,
                point_index=pt.index,
                player_side=side,
                shot_type=shot_type,
                result="in_play",
                t_start=round(hit.t, 3),
                frame_start=hit.frame,
                contact_court_xy=_round2(contact),
                bounce_court_xy=_round2(bounce),
                speed_kmh=hit.speed_kmh,
                depth_m=round(depth, 2) if depth is not None else None,
                lateral_m=round(bounce[0], 2) if bounce else None,
                direction=_direction(contact[0] if contact else None, bounce[0]) if bounce else None,
                net_clearance_idx=None,
                is_serve=(k == 0),
                serve_number=pt.serve_number if k == 0 else None,
                serve_zone=(
                    serve_zone(bounce[0], bounce[1], pt.server_side, pt.court_side)
                    if k == 0 and bounce else None
                ),
                rally_position=k,
                call=_call_for(pt, nxt_bounce),
            )
            pt_shots.append(shot)
            shots.append(shot)
            global_idx += 1

        _assign_results(pt, pt_shots)
        pt.shots = pt_shots
    return shots


def _round2(p: Optional[tuple[float, float]]) -> Optional[tuple[float, float]]:
    return (round(p[0], 2), round(p[1], 2)) if p else None


def _next_of(events: Sequence[BallEvent], after: BallEvent, kinds: tuple[str, ...]) -> Optional[BallEvent]:
    seen = False
    for e in events:
        if e is after:
            seen = True
            continue
        if seen and e.kind in kinds:
            return e
    return None


def _prev_of(events: Sequence[BallEvent], before: BallEvent, kinds: tuple[str, ...]) -> Optional[BallEvent]:
    out = None
    for e in events:
        if e is before:
            return out
        if e.kind in kinds:
            out = e
    return out


def _prev_flight(events, hits, k: int, fps: float) -> Optional[float]:
    """직전 샷의 체공 시간 (로브 -> 스매시 판정에 쓴다)."""
    if k == 0:
        return None
    prev_hit = hits[k - 1]
    b = _next_of(events, prev_hit, ("bounce",))
    if b is None:
        return None
    return (b.frame - prev_hit.frame) / max(fps, 1e-6)


def _classify(
    *, k: int, side: Side, contact, bounce, player_x, handed: str,
    volleyed: bool, near_net: bool, flight_s, prev_flight,
) -> ShotType:
    if k == 0:
        return "serve"
    if volleyed and near_net:
        if prev_flight is not None and prev_flight > LOB_FLIGHT_S:
            return "overhead"
        return "volley"
    if bounce is not None and abs(bounce[1]) < DROP_DEPTH_M and flight_s is not None and flight_s > 0.55:
        return "drop"
    if flight_s is not None and flight_s > LOB_FLIGHT_S and bounce is not None and abs(bounce[1]) > 6.0:
        return "lob"
    if k == 1:
        return "return"
    ball_x = contact[0] if contact else 0.0
    return _wing(ball_x, player_x, side, handed)


def _call_for(pt: PointRecord, bounce: Optional[BallEvent]):
    if bounce is None:
        return None
    for c in pt.calls:
        if c.frame == bounce.frame:
            return c
    return None


def _assign_results(pt: PointRecord, shots: list[Shot]) -> None:
    """포인트 종료 사유로부터 마지막 샷들의 결과를 정한다."""
    if not shots:
        return
    for s in shots:
        s.result = "in_play"
    last = shots[-1]
    reason = pt.end_reason

    if reason == "double_fault":
        last.result = "double_fault"
        return
    if reason == "ace":
        last.result = "ace"
        return
    if reason in ("out", "net"):
        # 마지막 친 사람이 실수한 것
        prev = shots[-2] if len(shots) >= 2 else None
        forced = _was_forced(prev, last)
        last.result = "forced_error" if forced else "unforced_error"
        if prev is not None:
            prev.result = "in_play"
        return
    if reason in ("double_bounce", "winner"):
        last.result = "winner"
        return
    last.result = "in_play"


def _was_forced(prev: Optional[Shot], last: Shot) -> bool:
    """강요된 실책인가 — 상대의 직전 샷이 빠르거나 깊거나 넓었는가."""
    if prev is None:
        return False
    fast = (prev.speed_kmh or 0) >= 85
    deep = (prev.depth_m or 0) >= 9.0
    wide = abs(prev.lateral_m or 0) >= SINGLES_HALF_W - 0.9
    hard_shot = prev.shot_type in ("overhead", "drop")
    return sum([fast, deep, wide, hard_shot]) >= 2


def rally_lengths(points: Sequence[PointRecord]) -> np.ndarray:
    return np.asarray([p.rally_length for p in points], dtype=float)


def shots_of(shots: Sequence[Shot], side: Side) -> list[Shot]:
    return [s for s in shots if s.player_side == side]


__all__ = ["build_shots", "shots_of", "rally_lengths", "NET_APPROACH_Y"]
