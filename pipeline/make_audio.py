# -*- coding: utf-8 -*-
"""요약 대본(script)을 edge-tts로 2인 대화 오디오(mp3)로 변환한다.

결과: docs/audio/{id}.mp3
"""
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AUDIO = ROOT / "docs" / "audio"


def load_config():
    return json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))


async def synth_line(text, voice):
    """한 줄을 합성해 mp3 바이트를 반환한다."""
    comm = edge_tts.Communicate(text, voice, rate="+8%")
    chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


async def make_episode(script, voices, out_path):
    parts = []
    for line in script:
        text = (line.get("text") or "").strip()
        if not text:
            continue  # 빈 줄이나 형식이 어긋난 줄은 건너뜀
        voice = voices.get(line.get("speaker"), list(voices.values())[0])
        for attempt in range(3):
            try:
                parts.append(await synth_line(text, voice))
                break
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
    # edge-tts는 동일 포맷(24kHz mono mp3)이라 단순 이어붙이기로 재생 가능
    out_path.write_bytes(b"".join(parts))


async def main():
    cfg = load_config()
    voices = cfg["tts_voices"]
    db = json.loads((DATA / "papers.json").read_text(encoding="utf-8"))
    AUDIO.mkdir(parents=True, exist_ok=True)
    done = 0
    sem = asyncio.Semaphore(3)

    async def run_one(summary):
        nonlocal done
        pid = summary["id"]
        out_path = AUDIO / f"{pid}.mp3"
        async with sem:
            try:
                await make_episode(summary["script"], voices, out_path)
                if pid in db:
                    db[pid]["status"] = "ready"
                done += 1
                print(f"[audio] 완료: {pid} ({out_path.stat().st_size // 1024}KB)", flush=True)
            except Exception as e:
                print(f"[audio] 실패: {pid}: {e}", file=sys.stderr, flush=True)
                if out_path.exists():
                    out_path.unlink()

    tasks = []
    for summary_file in sorted((DATA / "summaries").glob("*.json")):
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        if not (AUDIO / f"{summary['id']}.mp3").exists():
            tasks.append(run_one(summary))
    await asyncio.gather(*tasks)

    (DATA / "papers.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[audio] 신규 {done}건")


if __name__ == "__main__":
    asyncio.run(main())
