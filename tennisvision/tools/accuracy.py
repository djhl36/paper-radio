"""정확도 게이트 — 합성 경기의 정답과 파이프라인 출력을 층별로 비교한다.

"정확도"는 층마다 뜻이 다르고, 실제 코트에서 쓸 수 있느냐를 가르는 건 아래
순서대로 점점 더 엄격해진다.

  1. 바운스 검출      실제 바운스 중 몇 개를 찾았나 (재현율) / 찾은 것 중 몇 개가
                      진짜였나 (정밀도)
  2. 바운스 위치      찾은 바운스의 좌표 오차 (cm)
  3. 인/아웃 판정     찾은 바운스에 대해 인·아웃이 정답과 같은가
  4. 포인트           포인트 경계·승자·종료사유·랠리 길이가 맞는가
  5. 스코어           최종 스코어가 정답과 같은가

앱이 심판을 대신하려면 4·5번이 맞아야 한다. 3번이 아무리 좋아도 1번에서
바운스를 놓치면 포인트가 통째로 틀린다.

    python tools/accuracy.py --video data/sample_match.webm --target 0.98
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.geometry import (  # noqa: E402
    BALL_RADIUS,
    CALIBRATION_ORDER,
    rally_region,
    serve_target_box,
)
from engine.pipeline import analyze_match  # noqa: E402
from engine.vision.court import calibrate_manual  # noqa: E402


def opposite(side: str) -> str:
    return "far" if side == "near" else "near"


# --- 정답 재구성 -----------------------------------------------------------
def truth_points(truth: dict) -> list[dict]:
    """정답 이벤트에서 포인트별 승자·종료사유·랠리 길이·판정을 복원한다.

    시뮬레이터 규약:
      - shots[0] 은 서브, 이후 한 샷씩 번갈아 친다
      - outcome == "out" 이면 마지막 샷이 코트 밖에 떨어져 친 사람이 실점
      - 그 외에는 마지막 샷이 들어가고 두 번 튀어서 친 사람이 득점
    """
    by_point: dict[int, list[dict]] = {}
    for e in truth["truth"]:
        by_point.setdefault(e["point"], []).append(e)

    out: list[dict] = []
    for meta in truth["points"]:
        idx = meta["index"]
        evs = sorted(by_point.get(idx, []), key=lambda e: e["t"])
        hits = [e for e in evs if e["kind"] == "hit"]
        if not hits:
            continue
        server = meta["server"]
        court = meta["court"]
        n_shots = len(hits)
        last_hitter = server if (n_shots - 1) % 2 == 0 else opposite(server)
        if meta["outcome"] == "out":
            winner = opposite(last_hitter)
            end_reason = "out"
        else:
            winner = last_hitter
            end_reason = "ace" if n_shots == 1 else "double_bounce"

        # 각 샷의 착지 바운스(n==1)와 그때의 정답 인/아웃
        calls = []
        for k, hit in enumerate(hits):
            nxt = [e for e in evs if e["kind"] == "bounce" and e["t"] > hit["t"]]
            if not nxt:
                continue
            b = nxt[0]
            hitter = server if k % 2 == 0 else opposite(server)
            if k == 0:
                region = serve_target_box(server, court)  # type: ignore[arg-type]
            else:
                region = rally_region(opposite(hitter))  # type: ignore[arg-type]
            margin = region.signed_margin(b["x"], b["y"]) + BALL_RADIUS
            calls.append({
                "t": b["t"], "x": b["x"], "y": b["y"], "shot": k,
                "kind": "in" if margin >= 0 else ("fault" if k == 0 else "out"),
                "margin_cm": margin * 100,
            })

        out.append({
            "index": idx, "server_side": server, "court_side": court,
            "winner_side": winner, "end_reason": end_reason,
            "rally_length": n_shots,
            "t_start": hits[0]["t"], "t_end": evs[-1]["t"],
            "calls": calls,
        })
    return out


def truth_bounces(truth: dict) -> list[dict]:
    return [e for e in truth["truth"] if e["kind"] == "bounce"]


# --- 매칭 ------------------------------------------------------------------
def match_by_time(pred: list, truth: list, tol: float, key_p="t", key_t="t"):
    """시간 기준 1:1 최적 매칭(그리디, 가까운 쌍부터)."""
    pairs = []
    used_p, used_t = set(), set()
    cands = []
    for i, p in enumerate(pred):
        for j, t in enumerate(truth):
            dt = abs(p[key_p] - t[key_t])
            if dt <= tol:
                cands.append((dt, i, j))
    cands.sort()
    for dt, i, j in cands:
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        pairs.append((pred[i], truth[j], dt))
    return pairs, used_p, used_t


def pct(n: int, d: int) -> str:
    return f"{n}/{d} = {(n / d * 100) if d else 0:.1f}%"


def ratio(n: int, d: int) -> float:
    return (n / d) if d else 0.0


# --- 리포트 ----------------------------------------------------------------
def run(video: str, target: float, tol: float, max_frames: Optional[int]) -> dict:
    vp = Path(video)
    truth = json.loads(vp.with_suffix(".truth.json").read_text(encoding="utf-8"))
    calib = calibrate_manual(
        truth["court_corners_image"], list(CALIBRATION_ORDER), frame_size=tuple(truth["size"])
    )

    print("영상 분석 중…")
    analysis = analyze_match(
        video, calibration=calib, match_format="best_of_3",
        names={"near": "니어", "far": "파"},
        first_server_side=truth["points"][0]["server"],
        progress=lambda s, p: print(f"  [{p * 100:5.1f}%] {s}", end="\r"),
        max_frames=max_frames,
    )
    print(" " * 40, end="\r")

    tpoints = truth_points(truth)
    tbounces = truth_bounces(truth)
    scores: dict[str, float] = {}

    # 1) 바운스 검출 --------------------------------------------------------
    pred_calls = [
        {"t": c.t, "x": c.court_xy[0], "y": c.court_xy[1], "kind": c.kind,
         "too_close": c.too_close, "margin_cm": c.margin_cm}
        for c in analysis.calls
    ]
    pairs, used_p, used_t = match_by_time(pred_calls, tbounces, tol)
    recall = ratio(len(used_t), len(tbounces))
    precision = ratio(len(used_p), len(pred_calls))
    scores["bounce_recall"] = recall
    scores["bounce_precision"] = precision

    errs = np.array([np.hypot(p["x"] - t["x"], p["y"] - t["y"]) for p, t, _ in pairs]) * 100
    print("\n" + "=" * 66)
    print("1. 바운스 검출")
    print(f"   재현율(정답 중 찾은 비율)  {pct(len(used_t), len(tbounces))}")
    print(f"   정밀도(찾은 것 중 진짜)    {pct(len(used_p), len(pred_calls))}")
    if len(errs):
        print(f"   위치 오차  중앙값 {np.median(errs):.1f}cm · p90 {np.percentile(errs, 90):.1f}cm "
              f"· 최대 {errs.max():.1f}cm")
        scores["bounce_within_10cm"] = ratio(int((errs <= 10).sum()), len(errs))
        print(f"   10cm 이내  {pct(int((errs <= 10).sum()), len(errs))}")

    # 2) 인/아웃 판정 -------------------------------------------------------
    tcalls = [c for p in tpoints for c in p["calls"]]
    cpairs, cused_p, cused_t = match_by_time(pred_calls, tcalls, tol)
    ok = sum(1 for p, t, _ in cpairs if _same_call(p["kind"], t["kind"]))
    scores["call_accuracy"] = ratio(ok, len(cpairs))
    scores["call_coverage"] = ratio(len(cused_t), len(tcalls))
    print("\n2. 인/아웃 판정")
    print(f"   판정한 착지 바운스         {pct(len(cused_t), len(tcalls))}  (커버리지)")
    print(f"   그중 정답과 일치           {pct(ok, len(cpairs))}")
    wrong = [(p, t) for p, t, _ in cpairs if not _same_call(p["kind"], t["kind"])]
    for p, t in wrong[:5]:
        print(f"     t={t['t']:6.1f}s  정답 {t['kind']:5s}({t['margin_cm']:+7.1f}cm) "
              f"-> 판정 {p['kind']:5s}({p['margin_cm']:+8.1f}cm)")
    if len(wrong) > 5:
        print(f"     … 외 {len(wrong) - 5}건")

    # 3) 포인트 ------------------------------------------------------------
    pred_points = [
        {"t": (p.t_start + p.t_end) / 2, "t_start": p.t_start, "t_end": p.t_end,
         "winner_side": p.winner_side, "end_reason": p.end_reason,
         "rally_length": p.rally_length}
        for p in analysis.points
    ]
    tp_mid = [{**p, "t": (p["t_start"] + p["t_end"]) / 2} for p in tpoints]
    ppairs, pused_p, pused_t = match_by_time(pred_points, tp_mid, 3.0)
    win_ok = sum(1 for p, t, _ in ppairs if p["winner_side"] == t["winner_side"])
    reason_ok = sum(1 for p, t, _ in ppairs if p["end_reason"] == t["end_reason"])
    rally_ok = sum(1 for p, t, _ in ppairs if p["rally_length"] == t["rally_length"])

    scores["point_detection"] = ratio(len(pused_t), len(tpoints))
    scores["point_winner"] = ratio(win_ok, len(tpoints))       # 정답 전체 대비
    scores["point_end_reason"] = ratio(reason_ok, len(tpoints))
    scores["point_rally_length"] = ratio(rally_ok, len(tpoints))

    print("\n3. 포인트")
    print(f"   검출한 포인트              {pct(len(pused_t), len(tpoints))}"
          f"  (오검출 {len(pred_points) - len(pused_p)}개)")
    print(f"   승자 일치 (정답 전체 대비) {pct(win_ok, len(tpoints))}")
    print(f"   종료사유 일치              {pct(reason_ok, len(tpoints))}")
    print(f"   랠리 길이 일치             {pct(rally_ok, len(tpoints))}")
    print("\n   포인트별:")
    print("   " + "-" * 62)
    print(f"   {'#':>2}  {'정답':<26}  {'판정':<26}")
    pred_of_truth = {id(t): p for p, t, _ in ppairs}
    for t in tp_mid:
        p = pred_of_truth.get(id(t))
        gt = f"{t['winner_side']:<4} {t['end_reason']:<13} {t['rally_length']}구"
        if p is None:
            got = "(놓침)"
            mark = "X"
        else:
            got = f"{p['winner_side']:<4} {p['end_reason']:<13} {p['rally_length']}구"
            mark = "O" if (p["winner_side"] == t["winner_side"]
                           and p["end_reason"] == t["end_reason"]) else "~"
        print(f"   {t['index'] + 1:>2}  {gt:<26}  {got:<26}  {mark}")

    # 4) 스코어 ------------------------------------------------------------
    snap = (analysis.final_score or {}).get("snapshot", {})
    truth_score = _replay_truth_score(tpoints, truth["points"][0]["server"])
    got_score = snap.get("scoreString", "")
    scores["final_score"] = 1.0 if _norm_score(got_score) == _norm_score(truth_score) else 0.0
    print("\n4. 스코어")
    print(f"   정답 스코어  {truth_score}")
    print(f"   판정 스코어  {got_score}")

    # 5) 판정 ---------------------------------------------------------------
    print("\n" + "=" * 66)
    print(f"게이트 기준 {target * 100:.0f}%")
    gate = [
        ("바운스 검출 재현율", scores.get("bounce_recall", 0)),
        ("바운스 검출 정밀도", scores.get("bounce_precision", 0)),
        ("인/아웃 판정 정확도", scores.get("call_accuracy", 0)),
        ("포인트 검출률", scores.get("point_detection", 0)),
        ("포인트 승자 정확도", scores.get("point_winner", 0)),
        ("포인트 종료사유 정확도", scores.get("point_end_reason", 0)),
        ("최종 스코어 일치", scores.get("final_score", 0)),
    ]
    worst = 1.0
    for label, v in gate:
        mark = "PASS" if v >= target else "FAIL"
        worst = min(worst, v)
        print(f"   [{mark}] {label:<24} {v * 100:6.1f}%")
    print(f"\n   종합 판정: {'통과' if worst >= target else '미달'} "
          f"(가장 낮은 지표 {worst * 100:.1f}%)")
    print("=" * 66)
    return {"scores": scores, "worst": worst, "target": target}


def _same_call(pred_kind: str, truth_kind: str) -> bool:
    """fault 와 out 은 같은 '아웃' 계열로 본다(서브냐 랠리냐의 차이일 뿐)."""
    norm = {"fault": "out", "out": "out", "in": "in", "let": "in"}
    return norm.get(pred_kind, pred_kind) == norm.get(truth_kind, truth_kind)


def _norm_score(s: str) -> str:
    return (s or "").replace(" ", "")


def _replay_truth_score(tpoints: list[dict], first_server: str) -> str:
    """정답 포인트를 그대로 스코어보드에 넣었을 때 나와야 하는 스코어."""
    from engine.umpire.scoring import MatchFormat, ScoreBoard

    board = ScoreBoard(MatchFormat.preset("best_of_3"), first_server="A",
                       first_server_side=first_server)  # type: ignore[arg-type]
    for p in tpoints:
        board.award_point(board.player_at(p["winner_side"]), reason=p["end_reason"])
    return board.score_string()


def main() -> None:
    ap = argparse.ArgumentParser(description="합성 정답 대비 정확도 게이트")
    ap.add_argument("--video", default="data/sample_match.webm")
    ap.add_argument("--target", type=float, default=0.98)
    ap.add_argument("--tol", type=float, default=0.20, help="바운스 시간 매칭 허용 오차(초)")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--json", default=None, help="결과를 JSON 으로 저장")
    args = ap.parse_args()

    res = run(args.video, args.target, args.tol, args.max_frames)
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0 if res["worst"] >= res["target"] else 1)


if __name__ == "__main__":
    main()
