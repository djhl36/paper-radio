"""TennisVision 분석 엔진.

계층
    geometry   코트 규격/좌표계/호모그래피
    vision     코트 캘리브레이션, 공 추적, 선수 추적
    umpire     이벤트 -> 인/아웃 -> 포인트 -> 점수 (심판)
    analytics  샷 분석, 통계, 코칭 리포트, 플레이스타일 (코치)
    highlights 하이라이트 선정 및 클립 생성 (기자)
    pipeline   업로드 영상 전체 분석
    realtime   실시간 심판 세션
"""
from . import geometry, schema  # noqa: F401

__version__ = "0.1.0"
__all__ = ["geometry", "schema"]
