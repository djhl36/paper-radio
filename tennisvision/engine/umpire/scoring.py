"""테니스 점수 상태 머신.

규칙 범위
  - 포인트(0/15/30/40/AD), 듀스, 노애드(서든데스) 옵션
  - 게임, 세트(6게임 2게임차), 타이브레이크(기본 7점, 6-6에서)
  - 최종 세트: 일반 세트 / 타이브레이크 / 매치 타이브레이크(10점) / 애드밴티지 세트
  - 서브 순서(게임마다 교대, 타이브레이크는 1점 뒤 2점씩 교대)
  - 코트 교체(각 세트의 홀수 게임 후, 타이브레이크는 6점마다)
  - 듀스/애드 코트 계산, 폴트/더블폴트/레트

카메라 기준 near/far 와 선수 A/B 는 다르다(코트를 바꾸니까). 이 클래스가
`ends` 로 그 매핑을 들고 있고, 비전 계층은 항상 near/far 로만 말한다.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal, Optional

Player = Literal["A", "B"]
Side = Literal["near", "far"]
CourtSide = Literal["deuce", "ad"]

POINT_NAMES = {0: "0", 1: "15", 2: "30", 3: "40"}
FinalSetRule = Literal["normal", "tiebreak", "match_tiebreak", "advantage"]


def other(p: Player) -> Player:
    return "B" if p == "A" else "A"


@dataclass
class MatchFormat:
    sets_to_win: int = 2                    # 3세트 경기 = 2선승
    games_per_set: int = 6
    tiebreak_at: int = 6                    # 6-6 에서 타이브레이크
    tiebreak_points: int = 7
    ad_scoring: bool = True                 # False = 노애드(듀스에서 한 점 승부)
    final_set: FinalSetRule = "tiebreak"
    match_tiebreak_points: int = 10

    @classmethod
    def preset(cls, name: str) -> "MatchFormat":
        presets = {
            "best_of_3": cls(),
            "best_of_5": cls(sets_to_win=3),
            "pro_set": cls(sets_to_win=1, games_per_set=8, tiebreak_at=8),
            "one_set": cls(sets_to_win=1),
            "fast4": cls(sets_to_win=2, games_per_set=4, tiebreak_at=3, ad_scoring=False,
                         final_set="match_tiebreak"),
            "club_single_set_noad": cls(sets_to_win=1, ad_scoring=False),
        }
        if name not in presets:
            raise KeyError(f"알 수 없는 포맷: {name} (가능: {sorted(presets)})")
        return presets[name]


@dataclass
class SetScore:
    games: dict = field(default_factory=lambda: {"A": 0, "B": 0})
    tiebreak: Optional[dict] = None
    winner: Optional[Player] = None

    def as_tuple(self) -> tuple[int, int]:
        return self.games["A"], self.games["B"]


class ScoreBoard:
    def __init__(
        self,
        fmt: MatchFormat | None = None,
        first_server: Player = "A",
        names: Optional[dict] = None,
        first_server_side: Side = "near",
    ):
        self.fmt = fmt or MatchFormat()
        self.names = {"A": "Player A", "B": "Player B", **(names or {})}
        self.server: Player = first_server
        self.points: dict = {"A": 0, "B": 0}
        self.sets: list[SetScore] = [SetScore()]
        self.sets_won: dict = {"A": 0, "B": 0}
        self.in_tiebreak = False
        self.tiebreak_first_server: Optional[Player] = None
        self.point_index = 0
        self.game_index = 0
        self.serve_number = 1
        self.finished = False
        self.winner: Optional[Player] = None
        self.log: list[dict] = []
        receiver = other(first_server)
        self.ends: dict = {
            first_server: first_server_side,
            receiver: "far" if first_server_side == "near" else "near",
        }
        self._pending_changeover = False
        self._probe = False   # pressure() 내부 시뮬레이션 중 재귀 방지

    # --- 조회 -------------------------------------------------------------
    @property
    def current_set(self) -> SetScore:
        return self.sets[-1]

    def player_at(self, side: Side) -> Player:
        return "A" if self.ends["A"] == side else "B"

    def side_of(self, player: Player) -> Side:
        return self.ends[player]

    @property
    def receiver(self) -> Player:
        return other(self.server)

    def court_side(self) -> CourtSide:
        """다음 포인트를 시작하는 코트(서버 기준 듀스/애드)."""
        total = self.points["A"] + self.points["B"]
        return "deuce" if total % 2 == 0 else "ad"

    def _is_match_tiebreak(self) -> bool:
        return (
            self.in_tiebreak
            and self.fmt.final_set == "match_tiebreak"
            and self.sets_won["A"] == self.sets_won["B"] == self.fmt.sets_to_win - 1
        )

    def tiebreak_target(self) -> int:
        return self.fmt.match_tiebreak_points if self._is_match_tiebreak() else self.fmt.tiebreak_points

    # --- 표시 -------------------------------------------------------------
    def point_display(self) -> tuple[str, str]:
        a, b = self.points["A"], self.points["B"]
        if self.in_tiebreak:
            return str(a), str(b)
        if not self.fmt.ad_scoring:
            return POINT_NAMES.get(a, "40"), POINT_NAMES.get(b, "40")
        if a >= 3 and b >= 3:
            if a == b:
                return "40", "40"
            return ("AD", "-") if a > b else ("-", "AD")
        return POINT_NAMES.get(a, "40"), POINT_NAMES.get(b, "40")

    def score_string(self) -> str:
        sets = " ".join(f"{s.games['A']}-{s.games['B']}" for s in self.sets)
        pa, pb = self.point_display()
        if self.finished:
            return f"{sets} (승 {self.names[self.winner]})"
        return f"{sets} | {pa}-{pb}"

    def announce_ko(self) -> str:
        """서버 기준으로 읽는 한국어 콜."""
        if self.finished:
            return f"게임 세트 앤 매치, {self.names[self.winner]}"
        pa, pb = self.point_display()
        sp, rp = (pa, pb) if self.server == "A" else (pb, pa)
        if self.in_tiebreak:
            return f"{sp} 대 {rp}"
        if sp == "AD":
            return "어드밴티지 서버"
        if rp == "AD":
            return "어드밴티지 리시버"
        if sp == rp == "40":
            return "듀스"
        if sp == rp:
            return f"{sp} 올"
        return f"{sp} 대 {rp}"

    def snapshot(self) -> dict:
        pa, pb = self.point_display()
        return {
            "names": dict(self.names),
            "server": self.server,
            "serverSide": self.ends[self.server],
            "serveNumber": self.serve_number,
            "courtSide": self.court_side(),
            "points": {"A": pa, "B": pb},
            "rawPoints": dict(self.points),
            "games": [s.games.copy() for s in self.sets],
            "setsWon": dict(self.sets_won),
            "inTiebreak": self.in_tiebreak,
            "tiebreakTarget": self.tiebreak_target() if self.in_tiebreak else None,
            "ends": dict(self.ends),
            "finished": self.finished,
            "winner": self.winner,
            "scoreString": self.score_string(),
            "announce": self.announce_ko(),
            "pressure": {} if self._probe else self.pressure(),
            "pointIndex": self.point_index,
            "gameIndex": self.game_index,
        }

    # --- 압박 상황 --------------------------------------------------------
    def pressure(self) -> dict:
        """지금 진행할 포인트가 브레이크/세트/매치 포인트인지."""
        if self.finished or self._probe:
            return {"gamePoint": None, "breakPoint": None, "setPoint": None, "matchPoint": None}
        out: dict = {"gamePoint": None, "breakPoint": None, "setPoint": None, "matchPoint": None}
        for p in ("A", "B"):
            probe = copy.deepcopy(self)
            probe.log = []
            probe._probe = True
            res = probe.award_point(p)  # type: ignore[arg-type]
            if res["match_won"]:
                out["matchPoint"] = p
                out["setPoint"] = p
            elif res["set_won"]:
                out["setPoint"] = p
            if res["game_won"]:
                out["gamePoint"] = p
                if p == self.receiver and not self.in_tiebreak:
                    out["breakPoint"] = p
        return out

    # --- 진행 -------------------------------------------------------------
    def fault(self) -> dict:
        """서브 폴트. 두 번째 폴트면 더블폴트로 포인트가 넘어간다."""
        if self.finished:
            return {"double_fault": False, "state": self.snapshot()}
        if self.serve_number == 1:
            self.serve_number = 2
            return {"double_fault": False, "state": self.snapshot()}
        res = self.award_point(self.receiver, reason="double_fault")
        res["double_fault"] = True
        return res

    def let(self) -> dict:
        """레트 — 서브를 다시 넣는다(서브 번호 유지)."""
        return {"let": True, "state": self.snapshot()}

    def award_point(self, winner: Player, reason: str = "") -> dict:
        """포인트를 준다. 게임/세트/매치 종료를 함께 판정해 결과를 돌려준다."""
        if self.finished:
            return {
                "point_won": False, "game_won": False, "set_won": False, "match_won": False,
                "changeover": False, "state": self.snapshot(),
            }
        score_before = self.score_string()
        pressure_before = self.pressure()
        self.points[winner] += 1
        self.point_index += 1
        self.serve_number = 1

        game_won = set_won = match_won = False
        changeover = False
        ended_with_tiebreak = False

        if self.in_tiebreak:
            if self._tiebreak_complete(winner):
                game_won = True
                set_won = True
                ended_with_tiebreak = True
                self._close_set(winner, tiebreak=True)
            else:
                self._rotate_tiebreak_server()
                changeover = (self.points["A"] + self.points["B"]) % 6 == 0
                if changeover:
                    self._swap_ends()
        elif self._game_complete(winner):
            game_won = True
            self.current_set.games[winner] += 1
            self.game_index += 1
            self.points = {"A": 0, "B": 0}
            if self._set_complete(winner):
                set_won = True
                self._close_set(winner, tiebreak=False)
            elif self._should_start_tiebreak():
                self.in_tiebreak = True
                self.server = other(self.server)
                self.tiebreak_first_server = self.server
                self.current_set.tiebreak = {"A": 0, "B": 0}
                changeover = self._set_games_total() % 2 == 1
                if changeover:
                    self._swap_ends()
            else:
                self.server = other(self.server)
                changeover = self._set_games_total() % 2 == 1
                if changeover:
                    self._swap_ends()

        if set_won:
            match_won = self.sets_won[winner] >= self.fmt.sets_to_win
            games_in_set = self._set_games_total()
            if match_won:
                self.finished = True
                self.winner = winner
            else:
                # 타이브레이크로 끝난 세트: 타이브레이크에서 먼저 리시브한 쪽이 다음 세트 첫 서버
                if ended_with_tiebreak and self.tiebreak_first_server is not None:
                    self.server = other(self.tiebreak_first_server)
                else:
                    self.server = other(self.server)
                self.sets.append(SetScore())
                self.in_tiebreak = False
                self.tiebreak_first_server = None
                self.points = {"A": 0, "B": 0}
                # 세트 종료 시 그 세트의 총 게임 수가 홀수면 코트를 바꾼다
                changeover = games_in_set % 2 == 1
                if changeover:
                    self._swap_ends()
                self._maybe_start_deciding_tiebreak()

        if self.in_tiebreak and self.current_set.tiebreak is not None:
            self.current_set.tiebreak = dict(self.points)

        entry = {
            "index": self.point_index - 1,
            "winner": winner,
            "server": self.server,
            "reason": reason,
            "score_before": score_before,
            "score_after": self.score_string(),
            "game_won": game_won,
            "set_won": set_won,
            "match_won": match_won,
            "was_break_point": pressure_before["breakPoint"] == winner,
            "was_set_point": pressure_before["setPoint"] == winner,
            "was_match_point": pressure_before["matchPoint"] == winner,
        }
        self.log.append(entry)
        return {
            "point_won": True, "game_won": game_won, "set_won": set_won, "match_won": match_won,
            "changeover": changeover, "entry": entry, "state": self.snapshot(),
        }

    # --- 내부 -------------------------------------------------------------
    def _game_complete(self, winner: Player) -> bool:
        w, l = self.points[winner], self.points[other(winner)]
        if not self.fmt.ad_scoring:
            return w >= 4
        return w >= 4 and w - l >= 2

    def _tiebreak_complete(self, winner: Player) -> bool:
        target = self.tiebreak_target()
        w, l = self.points[winner], self.points[other(winner)]
        return w >= target and w - l >= 2

    def _set_games_total(self) -> int:
        return self.current_set.games["A"] + self.current_set.games["B"]

    def _set_complete(self, winner: Player) -> bool:
        g = self.current_set.games
        w, l = g[winner], g[other(winner)]
        return w >= self.fmt.games_per_set and w - l >= 2

    def _maybe_start_deciding_tiebreak(self) -> None:
        """최종 세트를 매치 타이브레이크로 치르는 포맷이면 0-0 에서 바로 시작한다."""
        if self.fmt.final_set != "match_tiebreak":
            return
        if self.sets_won["A"] != self.fmt.sets_to_win - 1 or self.sets_won["B"] != self.fmt.sets_to_win - 1:
            return
        self.in_tiebreak = True
        self.tiebreak_first_server = self.server
        self.current_set.tiebreak = {"A": 0, "B": 0}

    def _is_advantage_final_set(self) -> bool:
        return (
            self.fmt.final_set == "advantage"
            and self.sets_won["A"] == self.sets_won["B"] == self.fmt.sets_to_win - 1
        )

    def _should_start_tiebreak(self) -> bool:
        g = self.current_set.games
        if g["A"] != g["B"] or g["A"] < self.fmt.tiebreak_at:
            return False
        if self._is_advantage_final_set():
            return False
        return True

    def _close_set(self, winner: Player, tiebreak: bool) -> None:
        if tiebreak:
            self.current_set.games[winner] += 1
            self.current_set.tiebreak = dict(self.points)
            self.game_index += 1
        self.current_set.winner = winner
        self.sets_won[winner] += 1
        self.points = {"A": 0, "B": 0}
        self.in_tiebreak = False

    def _rotate_tiebreak_server(self) -> None:
        """타이브레이크: 첫 1점 뒤 2점마다 서브 교대."""
        total = self.points["A"] + self.points["B"]
        if total % 2 == 1:
            self.server = other(self.server)

    def _swap_ends(self) -> None:
        self.ends = {"A": self.ends["B"], "B": self.ends["A"]}

    # --- 직렬화 -----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": self.fmt.__dict__,
            "snapshot": self.snapshot(),
            "sets": [
                {"games": s.games, "tiebreak": s.tiebreak, "winner": s.winner} for s in self.sets
            ],
            "log": self.log,
        }


def start_match(
    fmt_name: str = "best_of_3",
    first_server: Player = "A",
    names: Optional[dict] = None,
    first_server_side: Side = "near",
) -> ScoreBoard:
    return ScoreBoard(MatchFormat.preset(fmt_name), first_server, names, first_server_side)


__all__ = ["MatchFormat", "ScoreBoard", "SetScore", "start_match", "other"]
