"""실시간 심판 세션.

폰 카메라가 프레임을 WebSocket 으로 보내면 서버가 이 세션에 밀어 넣고,
세션은 오버레이/판정/점수 메시지를 돌려준다.

지연
    공 검출기 1프레임 + 이벤트 창(W=5) + 비최대 억제(S=4) = 약 10프레임.
    30fps 기준 0.33초, 60fps 기준 0.17초 뒤에 판정이 확정된다. 공이 튄 뒤
    사람이 "아웃!"을 외치는 시간보다 빠르다.

오심 보정
    자동 판정은 틀릴 수 있으므로 `undo_point`, `award_manual`, `override_call`
    을 함께 제공한다. 실제 경기에서 쓰려면 이 되돌리기가 반드시 있어야 한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .analytics import playstyle as ps_mod
from .analytics import report as report_mod
from .analytics import shots as shots_mod
from .highlights import select as hl
from .schema import BallEvent, BallTrack, Calibration, MatchAnalysis, Side
from .umpire import bounce as bounce_mod
from .umpire.inout import explain
from .umpire.rally import Umpire, UmpireConfig
from .umpire.scoring import MatchFormat, ScoreBoard
from .vision.ball import BallTracker
from .vision.players import PlayerTracker


@dataclass
class LiveConfig:
    fps: float = 30.0
    doubles: bool = False
    camera_check_every: int = 300      # N 프레임마다 카메라 흔들림 확인
    emit_ball_every: int = 2           # 궤적 오버레이 전송 주기(프레임)
    event_cfg: bounce_mod.EventConfig = field(default_factory=bounce_mod.EventConfig)


class LiveSession:
    def __init__(
        self,
        calibration: Calibration,
        match_format: str = "best_of_3",
        names: Optional[dict] = None,
        first_server_side: Side = "near",
        cfg: LiveConfig | None = None,
        session_id: str = "live",
    ):
        self.cfg = cfg or LiveConfig()
        self.session_id = session_id
        self.calib = calibration
        self.names = {"near": "P1", "far": "P2", **(names or {})}
        self.first_server_side = first_server_side

        self.board = ScoreBoard(
            MatchFormat.preset(match_format),
            first_server="A",
            names={
                "A": self.names[first_server_side],
                "B": self.names["far" if first_server_side == "near" else "near"],
            },
            first_server_side=first_server_side,
        )
        self.track = BallTrack(positions=[], confidence=[], fps=self.cfg.fps)
        self.ground = bounce_mod.GroundTrack(calib=calibration, fps=self.cfg.fps)
        self.nadir = bounce_mod.camera_nadir(calibration)
        self.ball = BallTracker()
        self.players = PlayerTracker(calibration, doubles=self.cfg.doubles)
        self.umpire = Umpire(self.board, calibration, self.track, UmpireConfig(doubles=self.cfg.doubles))

        self.frame_index = -1
        self.started_at = time.time()
        self.breaks: dict[int, tuple[float, float, float, float]] = {}
        self.events: list[BallEvent] = []
        self.messages: list[dict] = []
        self._last_emitted_event_frame = -10
        self._emitted_call_frames: set[int] = set()
        self._camera_warned = False
        self._court_support_baseline: Optional[float] = None
        self._low_support_streak = 0

    # --- 프레임 입력 ------------------------------------------------------
    def push_frame(self, frame: np.ndarray) -> list[dict]:
        """프레임 1장을 처리하고 클라이언트로 보낼 메시지들을 돌려준다."""
        self.frame_index += 1
        i = self.frame_index
        out: list[dict] = []

        self.ball.update(frame, i)
        player_pos = self.players.update(frame, i)

        lag = getattr(self.ball.detector, "lag", 1)
        confirmed = i - lag
        self._append_track(confirmed)

        if confirmed >= 0 and confirmed % self.cfg.emit_ball_every == 0:
            p = self.track.at(confirmed)
            if p is not None:
                out.append({
                    "type": "ball",
                    "frame": confirmed,
                    "t": round(confirmed / self.cfg.fps, 3),
                    "image": [round(p[0], 1), round(p[1], 1)],
                })
        if player_pos and confirmed % 5 == 0:
            out.append({
                "type": "players",
                "frame": confirmed,
                "court": {s: (list(np.round(v, 2)) if v else None) for s, v in player_pos.items()},
            })

        out.extend(self._evaluate_events(confirmed, player_pos))

        out.extend(self._check_camera(frame, i))

        self.messages.extend(out)
        return out

    def _check_camera(self, frame: np.ndarray, i: int) -> list[dict]:
        """카메라가 흔들려 캘리브레이션이 깨졌는지 확인.

        절대 임계값은 코트 색/조명에 따라 오작동한다. 그래서 세션 시작 시점의
        코트 라인 일치도를 기준으로 잡고 **상대적으로 떨어졌을 때만** 경고한다.
        """
        if not self.cfg.camera_check_every:
            return []
        if i == 0 or i % self.cfg.camera_check_every != 0:
            return []
        from .vision.court import court_support

        support = court_support(self.calib, frame)
        if self._court_support_baseline is None:
            self._court_support_baseline = support
            return []
        base = max(self._court_support_baseline, 0.05)
        if support < base * 0.5:
            # 선수가 라인을 가리면 한 번쯤은 뚝 떨어질 수 있다. 연속 2회일 때만 경고한다.
            self._low_support_streak += 1
            if self._low_support_streak >= 2 and not self._camera_warned:
                self._camera_warned = True
                return [{
                    "type": "warning", "code": "camera_moved",
                    "message": "카메라가 움직인 것 같습니다. 코트 캘리브레이션을 다시 해주세요.",
                    "support": round(support, 3), "baseline": round(base, 3),
                }]
        else:
            self._low_support_streak = 0
            self._camera_warned = False
            self._court_support_baseline = max(base, support)
        return []

    def _append_track(self, confirmed: int) -> None:
        """확정 프레임까지 트랙 리스트를 채운다(결측은 None)."""
        while len(self.track.positions) <= confirmed:
            f = len(self.track.positions)
            p = self.ball.position_at(f)
            self.track.positions.append(p)
            self.track.confidence.append(self.ball.confidence_at(f))
            self.ground.append(p)

    # --- 이벤트 판정 ------------------------------------------------------
    def _evaluate_events(self, confirmed: int, player_pos: dict) -> list[dict]:
        """지연 = 검출기 1프레임 + 창 W + 비최대 억제 S 프레임."""
        cfg = self.cfg.event_cfg
        W, S = cfg.window, cfg.min_separation
        out: list[dict] = []

        k = confirmed - W                       # 양쪽 창이 다 찬 가장 최근 프레임
        if k < 0:
            return out
        if k not in self.breaks:
            self.breaks[k] = bounce_mod.break_at(self.ground, k, self.nadir, cfg)

        c = k - S                               # 비최대 억제까지 끝난 후보
        if c < 0 or c <= self._last_emitted_event_frame:
            return out
        mag, spd, rad, tan = self.breaks.get(c, (0.0, 0.0, 0.0, 0.0))
        threshold = max(cfg.min_break_ms, cfg.break_ratio * spd)
        if mag < threshold:
            return out
        window = [self.breaks.get(j, (0.0, 0.0, 0.0, 0.0))[0] for j in range(c - S, c + S + 1)]
        if mag < max(window) - 1e-9:
            return out

        ev = bounce_mod.classify_event(
            self.ground, self.calib, c, magnitude=mag, speed=spd, radial=rad, tangential=tan,
            player_positions=player_pos, cfg=cfg,
        )
        if ev is None:
            return out
        self._last_emitted_event_frame = c + S  # 같은 사건을 두 번 내보내지 않는다
        self._annotate_speed(ev)
        self.events.append(ev)
        out.append({
            "type": "event",
            "kind": ev.kind,
            "frame": ev.frame,
            "t": ev.t,
            "court": list(ev.court_xy) if ev.court_xy else None,
            "image": list(ev.image_xy),
            "bySide": ev.by_side,
            "speedKmh": ev.speed_kmh,
            "confidence": ev.confidence,
        })
        out.extend(self._feed_umpire(ev))
        return out

    def _annotate_speed(self, ev: BallEvent) -> None:
        if ev.kind not in ("bounce", "net") or ev.court_xy is None:
            return
        for prev in reversed(self.events):
            if prev.kind == "hit" and prev.court_xy is not None:
                dt = (ev.frame - prev.frame) / max(self.cfg.fps, 1e-6)
                if dt > 1e-3:
                    d = float(np.hypot(ev.court_xy[0] - prev.court_xy[0], ev.court_xy[1] - prev.court_xy[1]))
                    prev.speed_kmh = round(d / dt * 3.6, 1)
                return

    def _feed_umpire(self, ev: BallEvent) -> list[dict]:
        out: list[dict] = []
        res = self.umpire.feed(ev)

        # 판정은 포인트가 끝나야 umpire.calls 로 옮겨지므로 진행 중 포인트의
        # 판정까지 같이 훑되, 한 번 보낸 판정은 프레임 기준으로 다시 보내지 않는다.
        pending: list = list(self.umpire.calls)
        state = self.umpire._state  # noqa: SLF001
        if state is not None:
            pending.extend(state.calls)
        for call in pending:
            if call.frame in self._emitted_call_frames:
                continue
            self._emitted_call_frames.add(call.frame)
            out.append(self._call_message(call))

        if res:
            if res.get("fault"):
                out.append({"type": "fault", "serveNumber": self.board.serve_number,
                            "announce": "폴트", "score": self.board.snapshot()})
            elif res.get("let"):
                out.append({"type": "let", "announce": "레트", "score": self.board.snapshot()})
            elif "point" in res:
                pt = res["point"]
                out.append({
                    "type": "point",
                    "winnerSide": res["winner_side"],
                    "reason": res["reason"],
                    "rallyLength": pt.rally_length,
                    "point": pt.to_dict(),
                    "score": self.board.snapshot(),
                    "announce": self.board.announce_ko(),
                })
                if self.board.finished:
                    out.append({"type": "match_end", "score": self.board.snapshot()})
        return out

    def _call_message(self, call) -> dict:
        return {
            "type": "call",
            "kind": call.kind,
            "frame": call.frame,
            "t": call.t,
            "court": list(call.court_xy),
            "image": list(call.image_xy),
            "marginCm": call.margin_cm,
            "errorBudgetCm": call.error_budget_cm,
            "tooClose": call.too_close,
            "confidence": call.confidence,
            "announce": call.announce_ko(),
            "explain": explain(call),
        }

    # --- 수동 개입 --------------------------------------------------------
    def award_manual(self, side: Side, reason: str = "manual") -> dict:
        """자동 판정이 놓쳤을 때 사용자가 직접 포인트를 준다."""
        player = self.board.player_at(side)
        res = self.board.award_point(player, reason=reason)
        return {"type": "score", "score": res["state"], "manual": True,
                "announce": self.board.announce_ko()}

    def undo_point(self) -> dict:
        """마지막 포인트를 되돌린다(로그를 재생해 상태를 복원)."""
        if not self.board.log:
            return {"type": "score", "score": self.board.snapshot(), "undone": False}
        log = self.board.log[:-1]
        fmt = self.board.fmt
        names = self.board.names
        fresh = ScoreBoard(fmt, first_server="A", names=names,
                           first_server_side=self.first_server_side)
        for entry in log:
            fresh.award_point(entry["winner"], reason=entry.get("reason", ""))
        self.board = fresh
        self.umpire.board = fresh
        if self.umpire.points:
            self.umpire.points.pop()
            if self.umpire.point_events:
                self.umpire.point_events.pop()
        return {"type": "score", "score": self.board.snapshot(), "undone": True,
                "announce": self.board.announce_ko()}

    def override_call(self, frame: int, kind: str) -> dict:
        """특정 판정을 사용자가 뒤집는다(챌린지)."""
        for c in self.umpire.calls:
            if c.frame == frame:
                c.kind = kind  # type: ignore[assignment]
                c.reason += "|override"
                return {"type": "call_override", "frame": frame, "kind": kind}
        return {"type": "call_override", "frame": frame, "kind": kind, "found": False}

    def set_serve_number(self, n: int) -> dict:
        self.board.serve_number = max(1, min(2, int(n)))
        return {"type": "score", "score": self.board.snapshot()}

    # --- 상태/종료 --------------------------------------------------------
    def status(self) -> dict:
        return {
            "type": "status",
            "sessionId": self.session_id,
            "frames": self.frame_index + 1,
            "elapsed": round(time.time() - self.started_at, 1),
            "ballDetectionRatio": round(self.track.detected_ratio(), 3),
            "events": len(self.events),
            "points": len(self.umpire.points),
            "score": self.board.snapshot(),
            "calibrationQuality": self.calib.quality(),
        }

    def finish(self, match_id: Optional[str] = None) -> MatchAnalysis:
        """라이브 세션을 그대로 경기 분석 리포트로 마감한다."""
        self.umpire._flush_timeout(final=True)  # noqa: SLF001
        points = self.umpire.points
        shots = shots_mod.build_shots(points, self.umpire.point_events, self.players.tracks,
                                      fps=self.cfg.fps)
        duration = (self.frame_index + 1) / max(self.cfg.fps, 1e-6)
        stats: dict = {}
        reports: dict = {}
        styles: dict = {}
        conf = round(float(min(1.0, self.track.detected_ratio() / 0.55)), 3)
        for side in ("near", "far"):
            s = report_mod.compute_stats(
                side, points, shots, self.players.tracks.get(side),  # type: ignore[arg-type]
                fps=self.cfg.fps, name=self.names[side],
            )
            stats[side] = s.to_dict()
            reports[side] = report_mod.build_report(s, data_confidence=conf).to_dict()
            styles[side] = ps_mod.build_playstyle(s, self.names[side]).to_dict()
        clips = hl.select_highlights(points, names=self.names, duration=duration)
        return MatchAnalysis(
            match_id=match_id or self.session_id,
            fps=self.cfg.fps,
            duration=round(duration, 2),
            calibration=self.calib,
            points=points,
            shots=shots,
            calls=self.umpire.calls,
            highlights=clips,
            final_score=self.board.to_dict(),
            player_names=self.names,
            stats=stats,
            reports=reports,
            styles=styles,
            quality={
                "overall": conf,
                "ballDetectionRatio": round(self.track.detected_ratio(), 3),
                "calibration": self.calib.quality(),
                "pointsDetected": len(points),
                "usable": conf >= 0.5,
                "warnings": self.umpire.warnings,
                "source": "live",
            },
        )


__all__ = ["LiveSession", "LiveConfig"]
