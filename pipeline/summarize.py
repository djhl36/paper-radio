# -*- coding: utf-8 -*-
"""Claude CLI(헤드리스)로 각 논문의 한국어 요약 + 라디오 대본을 생성한다.

결과: data/summaries/{id}.json
  { "id", "title_ko", "one_liner", "summary_md", "script": [{"speaker","text"}, ...] }
"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SUMMARIES = DATA / "summaries"

PROMPT = """다음 학술 논문의 정보를 바탕으로, 한국어 요약과 2인 팟캐스트 라디오 대본을 만들어줘.

## 논문 정보
- 제목: {title}
- 저널: {journal} ({year})
- 저자: {authors}
- 소속: {affiliation}
- 초록:
{abstract}

## 출력 형식
아래 JSON 스키마로만 답해. 코드블록이나 다른 텍스트 없이 순수 JSON만 출력해.
{{
  "title_ko": "한국어로 번역한 논문 제목",
  "one_liner": "핵심 발견을 담은 한 줄 요약 (60자 이내)",
  "summary_md": "## 배경\\n...\\n\\n## 방법\\n...\\n\\n## 결과\\n...\\n\\n## 시사점\\n... (markdown, 총 400~700자, 수치는 구체적으로)",
  "script": [
    {{"speaker": "host_a", "text": "..."}},
    {{"speaker": "host_b", "text": "..."}}
  ]
}}

## 대본 규칙
- host_a는 진행자 수진(여), host_b는 전문가 민준(남). 12~18턴, 총 3~4분 분량.
- 첫 턴에서 수진이 저널명/연도와 함께 논문을 소개하고, 마지막 턴에서 실천적 시사점으로 마무리.
- 전문용어(JITAI, EMA, CGM 등)는 처음 나올 때 짧게 풀어서 설명.
- 구어체로 자연스럽게, 숫자 결과는 구체적으로 언급.
- TTS로 읽을 것이므로 특수문자·괄호·영어 약어 남발 금지 (영어 용어는 한글 발음 또는 한국어로).
"""


def load_config():
    return json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))


def call_claude(cli, prompt):
    proc = subprocess.run(
        ["cmd", "/c", cli, "-p", "--output-format", "text"],
        input=prompt.encode("utf-8"),
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
    out = proc.stdout.decode("utf-8", errors="replace")
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        raise ValueError("응답에서 JSON을 찾지 못함: " + out[:200])
    return json.loads(m.group(0))


def summarize_one(cfg, pid, paper):
    prompt = PROMPT.format(**paper)
    result = call_claude(cfg["claude_cli"], prompt)
    result["id"] = pid
    (SUMMARIES / f"{pid}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    cfg = load_config()
    db = json.loads((DATA / "papers.json").read_text(encoding="utf-8"))
    SUMMARIES.mkdir(parents=True, exist_ok=True)
    done = failed = 0

    todo = [
        (pid, paper) for pid, paper in db.items()
        if not (SUMMARIES / f"{pid}.json").exists()
        and len(paper.get("abstract", "")) >= 400  # 초록이 너무 짧으면(사설 등) 건너뜀
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(summarize_one, cfg, pid, paper): pid for pid, paper in todo}
        for fut in as_completed(futures):
            pid = futures[fut]
            try:
                fut.result()
                db[pid]["status"] = "summarized"
                done += 1
                print(f"[summarize] 완료: {pid}", flush=True)
            except Exception as e:
                failed += 1
                print(f"[summarize] 실패: {pid}: {e}", file=sys.stderr, flush=True)

    (DATA / "papers.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[summarize] 신규 {done}건, 실패 {failed}건")


if __name__ == "__main__":
    main()
