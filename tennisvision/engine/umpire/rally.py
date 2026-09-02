"""심판 상태 머신 — 이벤트 스트림을 포인트로 바꾼다.

입력  : `bounce.detect_events` 가 만든 BallEvent 시퀀스 (+ 플레이어 위치)
출력  : PointRecord 목록, LineCall 목록, 그리고 갱신된 ScoreBoard

포인트 종료 규칙
  아웃          : 랠리 바운스가 상대 코트 밖 -> 친 사람의 실점
  네트          : 공이 자기 진영에 떨어지거나 네트 이벤트 -> 친 사람의 실점
  더블 바운스   : 상대가 못 받아서 두 번 튐 -> 친 사람의 득점
  더블 폴트     : 서브 두 번 연속 폴트
  에이스        : 서브가 들어갔고 리시버의 타격 없이 두 번 튐

오프라인/실시간 모두 같은 클래스를 쓴다. 실시간에서는 `feed`, 오프라인에서는
`process_all` 을 호출한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..schema import BallEvent, BallTrack, Calibration, LineCall, PointRecord, Side
from . import inout
from .scoring import ScoreBoard


def opposite(side: Side) -> Side:
    return "far" if side == "near" else "near"


@dataclass
class UmpireConfig:
    doubles: bool = False
    min_gap_between_points_s: float = 1.2
    double_bounce_timeout_s: float = 1.6      # 바운스 후 이 시간 안에 타격이 없으면 못 받은 것
    trust_detected_server: bool = False       # True 면 첫 타격 사이드로 서버를 덮어쓴다
    allow_close_calls_as_in: bool = True      # too_close 판정을 인으로 처리(플레이 계속)


@dataclass
class PointState:
    index: int
    server_side: Side
    court_side: str
    serve_number: int = 1
    started: bool = False
    awaiting_serve: bool = False        # 폴트/레트 후 다음 서브를 기다리는 중
    serve_landed: bool = False
    last_hitter: Optional[Side] = None
    bounces_since_hit: int = 0
    shots_hits: list[BallEvent] = field(default_factory=list)
    calls: list[LineCall] = field(default_factory=list)
    events: list[BallEvent] = field(default_factory=list)
    t_start: float = 0.0
    frame_start: int = 0
    pending_let: bool = False


class Umpire:
    def __init__(
        self,
        board: ScoreBoard,
        calibration: Calibration,
        track: BallTrack,
        cfg: UmpireConfig | None = None,
    ):
        self.board = board
        self.calib = calibration
        self.track = track
        self.cfg = cfg or UmpireConfig()
        self.points: list[PointRecord] = []
        self.point_events: list[list[BallEvent]] = []   # points 와 인덱스가 1:1
        self.calls: list[LineCall] = []
        self.warnings: list[str] = []
        self._state: Optional[PointState] = None
        self._last_point_end_t = -1e9
        self._pending: list[BallEvent] = []

    # --- 공개 API ---------------------------------------------------------
    def process_all(self, events: Iterable[BallEvent]) -> list[PointRecord]:
        evs = list(events)
        for i, ev in enumerate(evs):
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            self.feed(ev, next_event=nxt)
        self._flush_timeout(final=True)
        if self._state is not None:          # 영상이 포인트 도중에 끝난 경우
            self.warnings.append("영상 끝에서 미완료 포인트를 버렸습니다")
            self._state = None
        return self.points

    def feed(self, ev: BallEvent, next_event: Optional[BallEvent] = None) -> Optional[dict]:
        """이벤트 하나를 먹는다. 포인트가 끝났으면 결과 dict 를 돌려준다."""
        if self._state is None:
            if ev.kind != "hit":
                return None
            if ev.t - self._last_point_end_t < self.cfg.min_gap_between_points_s:
                return None
            self._begin_point(ev)
            return None

        st = self._state

        # 폴트/레트 후: 다음 타격이 곧 다시 넣는 서브다. 그 사이 이벤트(공 줍기 등)는 무시.
        if st.awaiting_serve:
            if ev.kind != "hit":
                return None
            st.awaiting_serve = False
            st.serve_landed = False
            st.last_hitter = st.server_side
            st.bounces_since_hit = 0
            st.shots_hits = [ev]
            st.events.append(ev)
            st.court_side = self.board.court_side()
            st.serve_number = self.board.serve_number
            return None

        st.events.append(ev)

        # 직전 바운스 이후 타격 없이 시간이 오래 지났으면 못 받은 것으로 본다
        result = self._flush_timeout(now_t=ev.t)
        if result is not None and self._state is None:
            # 타임아웃으로 포인트가 끝났고, 이번 이벤트가 새 포인트의 서브일 수 있다
            if ev.kind == "hit" and ev.t - self._last_point_end_t >= self.cfg.min_gap_between_points_s:
                self._begin_point(ev)
            return result

        if ev.kind == "hit":
            return self._on_hit(ev)
        if ev.kind == "net":
            return self._on_net(ev)
        if ev.kind == "bounce":
            return self._on_bounce(ev, next_event)
        return None

    # --- 내부: 포인트 시작/종료 ------------------------------------------
    def _begin_point(self, serve_hit: BallEvent) -> None:
        board = self.board
        server_side = board.ends[board.server]
        if self.cfg.trust_detected_server and serve_hit.by_side:
            server_side = serve_hit.by_side
        elif serve_hit.by_side and serve_hit.by_side != server_side:
            self.warnings.append(
                f"t={serve_hit.t:.1f}s 서브 사이드 불일치 (스코어보드={server_side}, 검출={serve_hit.by_side})"
            )
        self._state = PointState(
            index=len(self.points),
            server_side=server_side,
            court_side=board.court_side(),
            serve_number=board.serve_number,
            started=True,
            last_hitter=server_side,
            t_start=serve_hit.t,
            frame_start=serve_hit.frame,
        )
        self._state.shots_hits.append(serve_hit)
        self._state.events.append(serve_hit)

    def _end_point(
        self, winner_side: Side, reason: str, ev: Optional[BallEvent],
        scoring: Optional[dict] = None,
    ) -> dict:
        """포인트를 마감한다.

        `scoring` 이 주어지면 점수는 이미 반영된 것으로 보고 다시 주지 않는다
        (더블폴트는 ScoreBoard.fault() 가 이미 포인트를 넘긴 상태다).
        """
        st = self._state
        assert st is not None
        board = self.board
        if scoring is None:
            winner_player = board.player_at(winner_side)
            scoring = board.award_point(winner_player, reason=reason)
        res = scoring
        entry = res.get("entry", {})
        t_end = ev.t if ev else st.t_start
        frame_end = ev.frame if ev else st.frame_start

        record = PointRecord(
            index=st.index,
            server_side=st.server_side,
            court_side=st.court_side,  # type: ignore[arg-type]
            winner_side=winner_side,
            end_reason=reason,  # type: ignore[arg-type]
            rally_length=len(st.shots_hits),
            t_start=round(st.t_start, 3),
            t_end=round(t_end, 3),
            frame_start=st.frame_start,
            frame_end=frame_end,
            score_before=entry.get("score_before", ""),
            score_after=entry.get("score_after", ""),
            is_break_point=bool(entry.get("was_break_point")),
            is_set_point=bool(entry.get("was_set_point")),
            is_match_point=bool(entry.get("was_match_point")),
            serve_number=st.serve_number,
            calls=list(st.calls),
        )
        record.shots = []          # analytics.shots 가 채운다
        self.points.append(record)
        self.point_events.append(list(st.events))
        self.calls.extend(st.calls)
        self._last_point_end_t = t_end
        self._state = None
        return {
            "point": record,
            "scoring": res,
            "winner_side": winner_side,
            "reason": reason,
            "hit_events": st.shots_hits,
            "events": st.events,
        }

    # --- 내부: 이벤트 처리 ------------------------------------------------
    def _on_hit(self, ev: BallEvent) -> Optional[dict]:
        st = self._state
        assert st is not None
        hitter = ev.by_side or opposite(st.last_hitter or st.server_side)

        # 상대가 안 넘긴 공을 자기가 다시 치는 경우는 없다고 보고, 같은 쪽 연속 타격은 무시
        if hitter == st.last_hitter and st.bounces_since_hit == 0:
            return None

        # 서브가 아직 안 떨어졌는데 리시버가 쳤다면 -> 서브가 들어간 것으로 간주
        if not st.serve_landed and hitter != st.server_side:
            st.serve_landed = True

        st.last_hitter = hitter
        st.bounces_since_hit = 0
        st.shots_hits.append(ev)
        return None

    def _on_net(self, ev: BallEvent) -> Optional[dict]:
        st = self._state
        assert st is not None
        hitter = st.last_hitter or st.server_side
        if not st.serve_landed and hitter == st.server_side:
            # 서브가 네트에 걸림 -> 폴트 (네트인 후 박스에 들어가면 레트지만
            # 그건 다음 바운스를 보고 판단하므로 여기서는 보류)
            st.pending_let = True
            return None
        return self._end_point(opposite(hitter), "net", ev)

    def _on_bounce(self, ev: BallEvent, next_event: Optional[BallEvent]) -> Optional[dict]:
        st = self._state
        assert st is not None
        if ev.court_xy is None:
            return None
        hitter = st.last_hitter or st.server_side

        # --- 서브 ---------------------------------------------------------
        if not st.serve_landed:
            call = inout.judge_serve(ev, self.track, self.calib, st.server_side, st.court_side)  # type: ignore[arg-type]
            st.calls.append(call)
            good = call.kind == "in" or (call.too_close and self.cfg.allow_close_calls_as_in)
            if st.pending_let:
                st.pending_let = False
                if good:
                    # 네트를 스치고 박스에 들어감 = 레트. 같은 서브 번호로 다시 넣는다.
                    self.board.let()
                    call.kind = "let"
                    self.warnings.append(f"t={ev.t:.1f}s 레트 (네트인 서브)")
                    st.awaiting_serve = True
                    st.serve_landed = False
                    st.bounces_since_hit = 0
                    return {"let": True, "call": call}
                return self._serve_fault(ev, call)
            if not good:
                return self._serve_fault(ev, call)
            st.serve_landed = True
            st.bounces_since_hit = 1
            return None

        # --- 랠리 ---------------------------------------------------------
        if inout.landed_on_own_side(ev, hitter):
            call = inout.judge_rally(ev, self.track, self.calib, hitter, self.cfg.doubles)
            call.kind = "out"
            call.reason = "net"
            st.calls.append(call)
            return self._end_point(opposite(hitter), "net", ev)

        call = inout.judge_rally(ev, self.track, self.calib, hitter, self.cfg.doubles)
        st.calls.append(call)
        if call.kind == "out" and not (call.too_close and self.cfg.allow_close_calls_as_in):
            return self._end_point(opposite(hitter), "out", ev)

        st.bounces_since_hit += 1
        if st.bounces_since_hit >= 2:
            reason = "ace" if len(st.shots_hits) == 1 else "double_bounce"
            return self._end_point(hitter, reason, ev)
        return None

    def _serve_fault(self, ev: BallEvent, call: LineCall) -> Optional[dict]:
        """폴트 처리. 두 번째 폴트면 더블폴트로 포인트가 끝난다."""
        st = self._state
        assert st is not None
        res = self.board.fault()
        if res.get("double_fault"):
            # fault() 안에서 이미 리시버에게 포인트가 넘어갔다
            return self._end_point(opposite(st.server_side), "double_fault", ev, scoring=res)
        # 세컨 서브로 같은 포인트를 이어간다 (점수/코트는 그대로, 서브만 다시)
        st.awaiting_serve = True
        st.serve_landed = False
        st.bounces_since_hit = 0
        st.serve_number = self.board.serve_number
        return {"fault": True, "call": call}

    # --- 타임아웃 ---------------------------------------------------------
    def _flush_timeout(self, now_t: float | None = None, final: bool = False) -> Optional[dict]:
        st = self._state
        if st is None or st.awaiting_serve:
            return None
        last_bounce = None
        for e in reversed(st.events):
            if e.kind == "bounce":
                last_bounce = e
                break
            if e.kind == "hit":
                break
        if last_bounce is None:
            if final:
                self._state = None
            return None
        if st.bounces_since_hit < 1:
            if final:
                self._state = None
            return None
        elapsed = (now_t - last_bounce.t) if now_t is not None else self.cfg.double_bounce_timeout_s
        if elapsed >= self.cfg.double_bounce_timeout_s or final:
            hitter = st.last_hitter or st.server_side
            reason = "ace" if len(st.shots_hits) == 1 else "winner"
            return self._end_point(hitter, reason, last_bounce)
        return None


def run_umpire(
    events: Iterable[BallEvent],
    board: ScoreBoard,
    calibration: Calibration,
    track: BallTrack,
    cfg: UmpireConfig | None = None,
) -> tuple[list[PointRecord], list[LineCall], list[str]]:
    ump = Umpire(board, calibration, track, cfg)
    ump.process_all(events)
    return ump.points, ump.calls, ump.warnings


__all__ = ["Umpire", "UmpireConfig", "run_umpire", "opposite"]
