"""합성 영상으로 파이프라인 정확도를 측정한다.

정답(.truth.json)과 비교해서
  - 바운스 검출 재현율 / 위치 오차(cm)
  - 이벤트 종류 정확도
  - 포인트 개수
를 출력한다. 알고리즘을 건드릴 때마다 이 숫자가 나빠지지 않는지 본다.

    python tools/evaluate.py --video data/sample_match.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.pipeline import analyze_match  # noqa: E402
from engine.vision.court import calibrate_manual  # noqa: E402
from engine.geometry import CALIBRATION_ORDER  # noqa: E402


def match_events(pred, truth, t_tol=0.25):
    """시간 기준으로 예측/정답 바운스를 1:1 매칭."""
    used = set()
    pairs = []
    for tr in truth:
        best = None
        for i, pr in enumerate(pred):
            if i in used:
                continue
            dt = abs(pr["t"] - tr["t"])
            if dt <= t_tol and (best is None or dt < best[0]):
                best = (dt, i)
        if best:
            used.add(best[1])
            pairs.append((tr, pred[best[1]]))
    return pairs, len(truth), len(pred)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="data/sample_match.webm")
    ap.add_argument("--out", default="data/sample_analysis.json")
    ap.add_argument("--max-frames", type=int, default=None)
    args = ap.parse_args()

    video = Path(args.video)
    truth_path = video.with_suffix(".truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    calib = calibrate_manual(truth["court_corners_image"], list(CALIBRATION_ORDER),
                             frame_size=tuple(truth["size"]))
    print(f"캘리브레이션 재투영 오차: {calib.reprojection_error_m * 100:.2f} cm ({calib.quality()})")

    analysis = analyze_match(
        str(video), calibration=calib, match_format="best_of_3",
        names={"near": "니어", "far": "파"}, first_server_side=truth["points"][0]["server"],
        progress=lambda s, p: print(f"  [{p * 100:5.1f}%] {s}", end="\r"),
        max_frames=args.max_frames,
    )
    print()

    # --- 바운스 위치 정확도 ---
    # 판정(call)은 바운스에서만 생기므로 call 을 예측 바운스로 쓴다
    pred = [{"t": c.t, "x": c.court_xy[0], "y": c.court_xy[1]} for c in analysis.calls]
    gt = [e for e in truth["truth"] if e["kind"] == "bounce"]
    pairs, n_gt, n_pred = match_events(pred, gt)
    if pairs:
        errs = np.array([np.hypot(p["x"] - t["x"], p["y"] - t["y"]) for t, p in pairs])
        print(f"바운스 매칭 {len(pairs)}/{n_gt} (검출 {n_pred}개)")
        print(f"  위치 오차  중앙값 {np.median(errs) * 100:.1f}cm  평균 {errs.mean() * 100:.1f}cm  "
              f"90퍼센타일 {np.percentile(errs, 90) * 100:.1f}cm")
    else:
        print("바운스를 하나도 매칭하지 못했습니다")

    print(f"공 검출률: {analysis.quality['ballDetectionRatio'] * 100:.1f}%")
    print(f"검출 포인트 {len(analysis.points)}개 (정답 {len(truth['points'])}개)")
    print(f"최종 스코어: {analysis.final_score['snapshot']['scoreString']}")
    print(f"하이라이트 {len(analysis.highlights)}개")
    for side in ("near", "far"):
        r = analysis.reports[side]
        print(f"  [{side}] {r['headline']} / 스타일 {analysis.styles[side]['archetype_ko']}")
    print(f"분석 신뢰도: {analysis.quality['overall']}  ({analysis.quality['message']})")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(analysis.to_json(indent=2), encoding="utf-8")
    print(f"분석 결과 저장: {args.out}")


if __name__ == "__main__":
    main()
