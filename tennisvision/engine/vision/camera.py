"""코트 캘리브레이션에서 전체 카메라(내부 파라미터 + 자세)를 복원한다.

지면 호모그래피만으로는 공의 **높이**를 알 수 없다. 공중에 뜬 공을 지면에
투영하면 실제보다 카메라에서 먼 쪽으로 밀려서 찍히기 때문에, 바운스가 아닌
순간의 좌표는 전부 틀린 값이다. 그래서 코트라는 알려진 평면 패턴으로 카메라를
캘리브레이션해서 3D 광선을 얻고, `trajectory.py` 에서 물리 제약과 함께 풀어
공의 3D 궤적을 복원한다.

코트는 평면이므로 단일 뷰 캘리브레이션이 가능하다(주점은 화면 중앙, 왜곡 0,
정방 픽셀로 고정하고 초점거리 1개 + 자세 6개만 추정).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from ..schema import Calibration


@dataclass
class CameraModel:
    K: np.ndarray            # 3x3 내부 파라미터
    R: np.ndarray            # 3x3 회전 (월드 -> 카메라)
    t: np.ndarray            # 3, 이동 (월드 -> 카메라)
    reproj_px: float         # 캘리브레이션 재투영 오차(px)
    frame_size: tuple[int, int]

    @property
    def position(self) -> np.ndarray:
        """카메라의 월드 좌표(코트 좌표계, m)."""
        return -self.R.T @ self.t

    @property
    def height(self) -> float:
        return float(self.position[2])

    @property
    def nadir(self) -> tuple[float, float]:
        """카메라 바로 아래 지면 지점 (코트 좌표)."""
        p = self.position
        return float(p[0]), float(p[1])

    def ray(self, u: float, v: float) -> np.ndarray:
        """이미지 점을 지나는 월드 좌표계 단위 방향 벡터."""
        d_cam = np.linalg.inv(self.K) @ np.array([u, v, 1.0])
        d_world = self.R.T @ d_cam
        n = np.linalg.norm(d_world)
        return d_world / (n if n else 1.0)

    def rays(self, pts: Sequence[Sequence[float]]) -> np.ndarray:
        """(N,2) 이미지 점 -> (N,3) 월드 방향."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        hom = np.hstack([p, np.ones((len(p), 1))])
        d_cam = (np.linalg.inv(self.K) @ hom.T).T
        d_world = (self.R.T @ d_cam.T).T
        norms = np.linalg.norm(d_world, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return d_world / norms

    def project(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """(N,3) 월드 좌표 -> (N,2) 이미지 좌표."""
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        cam = (self.R @ p.T).T + self.t
        z = np.clip(cam[:, 2:3], 1e-6, None)
        img = (self.K @ (cam / z).T).T
        return img[:, :2]

    def ground_point(self, u: float, v: float) -> tuple[float, float]:
        """이미지 점을 지면(z=0)으로 역투영."""
        C = self.position
        d = self.ray(u, v)
        if abs(d[2]) < 1e-9:
            return float("nan"), float("nan")
        s = -C[2] / d[2]
        p = C + s * d
        return float(p[0]), float(p[1])

    def to_dict(self) -> dict:
        return {
            "K": self.K.tolist(), "R": self.R.tolist(), "t": self.t.tolist(),
            "position": self.position.tolist(), "height": round(self.height, 3),
            "nadir": [round(x, 3) for x in self.nadir],
            "reprojPx": round(self.reproj_px, 3), "frameSize": list(self.frame_size),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CameraModel":
        return cls(
            K=np.asarray(d["K"], float), R=np.asarray(d["R"], float),
            t=np.asarray(d["t"], float), reproj_px=float(d.get("reprojPx", 0.0)),
            frame_size=tuple(d.get("frameSize", (0, 0))),
        )


def estimate_camera(
    calib: Calibration,
    frame_size: Optional[tuple[int, int]] = None,
    focal_guess: Optional[float] = None,
) -> Optional[CameraModel]:
    """코트 대응점으로 카메라를 추정한다. 실패하면 None(2D 폴백)."""
    size = frame_size or calib.frame_size
    if not size or size[0] <= 0:
        return None
    w, h = int(size[0]), int(size[1])
    img = np.asarray(calib.image_points, dtype=np.float32).reshape(-1, 1, 2)
    obj = np.asarray(
        [(x, y, 0.0) for x, y in calib.court_points], dtype=np.float32
    ).reshape(-1, 1, 3)
    if len(img) < 4:
        return None

    f0 = float(focal_guess or (0.9 * max(w, h)))
    K0 = np.array([[f0, 0, w / 2.0], [0, f0, h / 2.0], [0, 0, 1.0]], dtype=np.float64)
    dist0 = np.zeros((5, 1), dtype=np.float64)
    flags = (
        cv2.CALIB_USE_INTRINSIC_GUESS
        | cv2.CALIB_FIX_PRINCIPAL_POINT
        | cv2.CALIB_FIX_ASPECT_RATIO
        | cv2.CALIB_ZERO_TANGENT_DIST
        | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3
    )
    try:
        rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
            [obj], [img], (w, h), K0, dist0, flags=flags
        )
    except cv2.error:
        return None
    if not rvecs:
        return None
    R, _ = cv2.Rodrigues(rvecs[0])
    t = np.asarray(tvecs[0], dtype=np.float64).reshape(3)
    cam = CameraModel(K=np.asarray(K, float), R=R, t=t, reproj_px=float(rms), frame_size=(w, h))

    # 물리적으로 말이 되는지 확인: 카메라는 지면 위 1.5~30m, 코트 바깥 어딘가
    pos = cam.position
    if not (1.0 < pos[2] < 40.0) or not np.isfinite(pos).all():
        return None
    if cam.reproj_px > max(6.0, 0.01 * max(w, h)):
        return None
    return cam


def refine_with_extra_points(
    calib: Calibration, extra_image: Sequence[Sequence[float]],
    extra_court: Sequence[Sequence[float]], frame_size: tuple[int, int]
) -> Optional[CameraModel]:
    """서비스라인 T 등 추가 점을 더해 카메라 추정을 개선한다."""
    merged = Calibration(
        homography=calib.homography,
        image_points=list(calib.image_points) + [tuple(p) for p in extra_image],
        court_points=list(calib.court_points) + [tuple(p) for p in extra_court],
        landmark_names=list(calib.landmark_names) + ["extra"] * len(extra_image),
        reprojection_error_m=calib.reprojection_error_m,
        method=calib.method,
        frame_size=frame_size,
    )
    return estimate_camera(merged, frame_size)


__all__ = ["CameraModel", "estimate_camera", "refine_with_extra_points"]
