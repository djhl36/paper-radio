# -*- coding: utf-8 -*-
"""전체 파이프라인 실행: 수집 → 요약 → 오디오 → 사이트 빌드"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = ["fetch_papers.py", "summarize.py", "make_audio.py", "build_site.py"]

for step in STEPS:
    print(f"\n===== {step} =====")
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / step)])
    if r.returncode != 0:
        print(f"[run] {step} 실패 (계속 진행)", file=sys.stderr)

print("\n[run] 파이프라인 완료")
