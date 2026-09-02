"""플러그형 검출기 레지스트리.

엔진은 구체 모델을 직접 부르지 않고 아래 프로토콜만 안다. 기본 구현은
가중치 다운로드 없이 즉시 동작하는 OpenCV 기반이고, 가중치를 준비하면
`register_ball_detector("tracknet", ...)` 처럼 꽂아 넣어 정확도를 올린다.

    from engine.vision import detectors
    detectors.use("ball", "tracknet", weights="models/tracknet.pt")
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

import numpy as np

from ..schema import Detection


@runtime_checkable
class BallDetector(Protocol):
    """프레임을 순서대로 먹고 공 후보를 뱉는다. 1프레임 지연 허용."""

    def reset(self) -> None: ...

    def push(self, frame: np.ndarray, frame_index: int) -> list[Detection]:
        """이번 호출로 확정된 (frame_index - lag) 프레임의 후보들."""
        ...

    @property
    def lag(self) -> int: ...


@runtime_checkable
class PlayerDetector(Protocol):
    def detect(self, frame: np.ndarray, frame_index: int) -> list[Detection]: ...


_BALL_FACTORIES: dict[str, Callable[..., BallDetector]] = {}
_PLAYER_FACTORIES: dict[str, Callable[..., PlayerDetector]] = {}
_ACTIVE: dict[str, tuple[str, dict]] = {"ball": ("motion", {}), "player": ("motion", {})}


def register_ball_detector(name: str, factory: Callable[..., BallDetector]) -> None:
    _BALL_FACTORIES[name] = factory


def register_player_detector(name: str, factory: Callable[..., PlayerDetector]) -> None:
    _PLAYER_FACTORIES[name] = factory


def use(kind: str, name: str, **kwargs) -> None:
    """이후 생성되는 검출기의 구현을 바꾼다."""
    table = _BALL_FACTORIES if kind == "ball" else _PLAYER_FACTORIES
    if name not in table:
        raise KeyError(f"등록되지 않은 {kind} 검출기: {name} (가능: {sorted(table)})")
    _ACTIVE[kind] = (name, kwargs)


def available(kind: str) -> list[str]:
    return sorted(_BALL_FACTORIES if kind == "ball" else _PLAYER_FACTORIES)


def make_ball_detector(**overrides) -> BallDetector:
    name, kw = _ACTIVE["ball"]
    return _BALL_FACTORIES[name](**{**kw, **overrides})


def make_player_detector(**overrides) -> PlayerDetector:
    name, kw = _ACTIVE["player"]
    return _PLAYER_FACTORIES[name](**{**kw, **overrides})


# --- 선택적 딥러닝 어댑터 --------------------------------------------------
class YoloPlayerDetector:
    """ultralytics YOLO 로 사람 박스를 뽑는다. 설치/가중치가 있을 때만 동작."""

    def __init__(self, weights: str = "yolov8n.pt", conf: float = 0.35, device: str = "cpu"):
        from ultralytics import YOLO  # 지연 임포트: 없으면 여기서만 실패

        self.model = YOLO(weights)
        self.conf = conf
        self.device = device

    def detect(self, frame: np.ndarray, frame_index: int) -> list[Detection]:
        res = self.model.predict(frame, conf=self.conf, classes=[0], verbose=False, device=self.device)
        out: list[Detection] = []
        for r in res:
            for b in r.boxes:
                x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
                out.append(
                    Detection(
                        frame=frame_index,
                        x=(x1 + x2) / 2,
                        y=y2,                      # 발 위치 = 박스 하단 중앙
                        confidence=float(b.conf[0]),
                        w=x2 - x1,
                        h=y2 - y1,
                        source="yolo",
                    )
                )
        return out


class TrackNetBallDetector:
    """TrackNet 계열(3프레임 입력 -> 히트맵) 어댑터.

    체크포인트마다 전처리가 달라서, 실제 가중치를 붙일 때 `preprocess`/`postprocess`
    만 교체하면 되도록 얇게 유지했다.
    """

    def __init__(self, weights: str, size: tuple[int, int] = (640, 360), device: str = "cpu",
                 threshold: float = 0.5):
        import torch  # 지연 임포트

        self.torch = torch
        self.device = device
        self.size = size
        self.threshold = threshold
        self.model = torch.jit.load(weights, map_location=device) if weights.endswith(".pt") \
            else torch.load(weights, map_location=device)
        self.model.eval()
        self._buf: list[np.ndarray] = []
        self._orig: Optional[tuple[int, int]] = None

    @property
    def lag(self) -> int:
        return 1

    def reset(self) -> None:
        self._buf.clear()

    def push(self, frame: np.ndarray, frame_index: int) -> list[Detection]:
        import cv2

        self._orig = frame.shape[1], frame.shape[0]
        self._buf.append(cv2.resize(frame, self.size))
        if len(self._buf) < 3:
            return []
        if len(self._buf) > 3:
            self._buf.pop(0)
        stack = np.concatenate([f[:, :, ::-1] for f in self._buf], axis=2).astype(np.float32) / 255.0
        t = self.torch.from_numpy(stack.transpose(2, 0, 1))[None].to(self.device)
        with self.torch.no_grad():
            heat = self.model(t)
        heat = heat.squeeze().cpu().numpy()
        if heat.ndim == 3:
            heat = heat[-1]
        peak = float(heat.max())
        if peak < self.threshold:
            return []
        yi, xi = np.unravel_index(int(heat.argmax()), heat.shape)
        sx = self._orig[0] / heat.shape[1]
        sy = self._orig[1] / heat.shape[0]
        return [
            Detection(
                frame=frame_index - self.lag,
                x=float(xi * sx),
                y=float(yi * sy),
                confidence=peak,
                source="tracknet",
            )
        ]


def try_register_optional() -> list[str]:
    """설치된 선택 의존성만 골라 등록한다. 실패는 조용히 넘어간다."""
    ok: list[str] = []
    try:
        import ultralytics  # noqa: F401

        register_player_detector("yolo", YoloPlayerDetector)
        ok.append("yolo")
    except Exception:
        pass
    try:
        import torch  # noqa: F401

        register_ball_detector("tracknet", TrackNetBallDetector)
        ok.append("tracknet")
    except Exception:
        pass
    return ok


__all__ = [
    "BallDetector",
    "PlayerDetector",
    "register_ball_detector",
    "register_player_detector",
    "use",
    "available",
    "make_ball_detector",
    "make_player_detector",
    "try_register_optional",
    "YoloPlayerDetector",
    "TrackNetBallDetector",
]
