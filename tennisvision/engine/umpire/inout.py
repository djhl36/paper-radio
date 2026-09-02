"""인/아웃 판정.

판정은 결정론적 불리언이 아니라 **불확실성을 가진 추정**이다. 실제 호크아이도
공칭 오차 ±3.6mm 를 공표한다. 여기서는 캘리브레이션 오차 + 프레임 샘플링 한계 +
검출 오차를 합쳐 1시그마 오차 예산을 만들고,

    P(인) = Phi( (라인까지의 여유 + 공 반지름) / sigma )

로 확률을 낸다. 여유가 오차 예산 안이면 `too_close=True` 로 표시해서 앱이
"판독 불가 — 다시 플레이" 를 띄우거나 사용자 확인을 받게 한다. 애매한 판정을
확신에 찬 콜처럼 내보내지 않는 것이 이 모듈의 설계 원칙이다.
"""
from __future__ import annotations

import math

from ..geometry import (
    BALL_RADIUS,
    CourtSide,
    Region,
    Side,
    rally_region,
    serve_target_box,
    serve_zone,
)
from ..schema import BallEvent, BallTrack, Calibration, LineCall
from .bounce import bounce_uncertainty_cm


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def judge_point(
    court_xy: tuple[float, float],
    image_xy: tuple[float, float],
    region: Region,
    error_budget_cm: float,
    frame: int,
    t: float,
    is_serve: bool = False,
    close_sigma: float = 1.0,
) -> LineCall:
    """코트 좌표 1점에 대한 판정."""
    margin_m = region.signed_margin(*court_xy)
    # 공이 라인에 스치기만 해도 인 -> 경계를 공 반지름만큼 바깥으로 확장
    effective_m = margin_m + BALL_RADIUS
    sigma_cm = max(error_budget_cm, 0.5)
    margin_cm = effective_m * 100.0

    p_in = _phi(margin_cm / sigma_cm)
    too_close = abs(margin_cm) < close_sigma * sigma_cm

    if effective_m >= 0:
        kind = "in"
        confidence = p_in
    else:
        kind = "fault" if is_serve else "out"
        confidence = 1.0 - p_in

    return LineCall(
        kind=kind,  # type: ignore[arg-type]
        confidence=round(float(confidence), 4),
        margin_cm=round(float(margin_cm), 1),
        court_xy=(round(court_xy[0], 3), round(court_xy[1], 3)),
        image_xy=(round(image_xy[0], 1), round(image_xy[1], 1)),
        region=region.name,
        nearest_line=region.nearest_line(*court_xy),
        frame=frame,
        t=round(t, 3),
        error_budget_cm=round(float(sigma_cm), 1),
        too_close=bool(too_close),
        reason="serve" if is_serve else "rally",
    )


def judge_serve(
    event: BallEvent,
    track: BallTrack,
    calib: Calibration,
    server_side: Side,
    court_side: CourtSide,
) -> LineCall:
    """서브 바운스 판정 (해당 서비스 박스 기준)."""
    assert event.court_xy is not None
    box = serve_target_box(server_side, court_side)
    sigma = _sigma_for(event, track, calib)
    call = judge_point(
        event.court_xy, event.image_xy, box, sigma, event.frame, event.t, is_serve=True
    )
    call.reason = f"serve/{court_side}/{serve_zone(event.court_xy[0], event.court_xy[1], server_side, court_side)}"
    return call


def judge_rally(
    event: BallEvent,
    track: BallTrack,
    calib: Calibration,
    hitter_side: Side,
    doubles: bool = False,
) -> LineCall:
    """랠리 중 바운스 판정 (상대 진영 전체 기준)."""
    assert event.court_xy is not None
    receiver: Side = "far" if hitter_side == "near" else "near"
    region = rally_region(receiver, doubles=doubles)
    sigma = _sigma_for(event, track, calib)
    return judge_point(event.court_xy, event.image_xy, region, sigma, event.frame, event.t)


def _sigma_for(event: BallEvent, track: BallTrack, calib: Calibration) -> float:
    """이벤트 확신도까지 반영한 오차 예산.

    바운스 검출 자체가 불확실하면 판정도 그만큼 흐려야 한다. 확신도가 낮은
    이벤트에 자신 있는 아웃 콜을 내보내는 것이 이 시스템에서 제일 나쁜 실패다.
    그래서 예산을 1/confidence 로 부풀려 `too_close`(판독 불가)로 떨어지게 한다.
    """
    base = bounce_uncertainty_cm(track, calib, event.frame, event.image_xy)
    conf = float(min(max(event.confidence, 0.15), 1.0))
    return base / conf


def landed_on_own_side(event: BallEvent, hitter_side: Side) -> bool:
    """공이 친 사람 자기 진영에 떨어졌다 (= 네트를 못 넘었다)."""
    if event.court_xy is None:
        return False
    y = event.court_xy[1]
    return (y < 0) if hitter_side == "near" else (y > 0)


def explain(call: LineCall) -> str:
    """앱/음성 안내용 한국어 설명."""
    line_ko = {
        "left": "왼쪽 사이드라인", "right": "오른쪽 사이드라인",
        "near": "니어 라인", "far": "베이스라인",
    }.get(call.nearest_line, call.nearest_line)
    if call.too_close:
        return (
            f"판독 불가 — {line_ko}에서 {abs(call.margin_cm):.0f}cm "
            f"(이 카메라의 오차 ±{call.error_budget_cm:.0f}cm)"
        )
    verb = {"in": "인", "out": "아웃", "fault": "폴트", "let": "레트"}.get(call.kind, call.kind)
    side = "안쪽" if call.margin_cm >= 0 else "바깥"
    return f"{verb} — {line_ko} {side} {abs(call.margin_cm):.0f}cm (확신도 {call.confidence * 100:.0f}%)"


__all__ = ["judge_point", "judge_serve", "judge_rally", "landed_on_own_side", "explain"]
