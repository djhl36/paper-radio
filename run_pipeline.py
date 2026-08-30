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

print("\n===== deploy =====")
r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
if r.stdout.strip():
    subprocess.run(["git", "-C", str(ROOT), "add", "-A"])
    subprocess.run(["git", "-C", str(ROOT), "commit", "-m", "주간 자동 업데이트: 신규 논문·오디오 추가"])
    p = subprocess.run(["git", "-C", str(ROOT), "push"])
    print("[deploy] GitHub Pages 배포 완료" if p.returncode == 0 else "[deploy] push 실패", file=sys.stderr if p.returncode else sys.stdout)
else:
    print("[deploy] 변경 사항 없음")

print("\n[run] 파이프라인 완료")
