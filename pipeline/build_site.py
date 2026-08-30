# -*- coding: utf-8 -*-
"""papers.json + summaries + audio를 모아 웹앱 데이터(app-data.json)와 팟캐스트 RSS(feed.xml)를 생성한다."""
import email.utils
import json
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"


def load_config():
    return json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))


def build_app_data(db):
    items = []
    for pid, p in db.items():
        summary_path = DATA / "summaries" / f"{pid}.json"
        audio_path = DOCS / "audio" / f"{pid}.mp3"
        item = {
            "id": pid,
            "title": p["title"],
            "year": p["year"],
            "pub_date": p.get("pub_date", ""),
            "journal": p["journal"],
            "authors": p["authors"],
            "affiliation": p.get("affiliation", ""),
            "topics": p["topics"],
            "url": p["url"] if isinstance(p["url"], str) else "",
            "has_audio": audio_path.exists(),
        }
        if summary_path.exists():
            s = json.loads(summary_path.read_text(encoding="utf-8"))
            item["title_ko"] = s.get("title_ko", "")
            item["one_liner"] = s.get("one_liner", "")
            item["summary_md"] = s.get("summary_md", "")
        items.append(item)
    items.sort(key=lambda x: x["pub_date"], reverse=True)
    return items


def build_feed(cfg, items):
    base = cfg.get("site_base_url", "").rstrip("/")
    now = email.utils.formatdate(usegmt=True)
    entries = []
    for it in items:
        if not it["has_audio"]:
            continue
        mp3 = DOCS / "audio" / f"{it['id']}.mp3"
        audio_url = f"{base}/audio/{it['id']}.mp3" if base else f"audio/{it['id']}.mp3"
        page_url = f"{base}/#p/{it['id']}" if base else f"#p/{it['id']}"
        try:
            pub = email.utils.formatdate(
                time.mktime(time.strptime(it["pub_date"], "%Y-%m-%d")), usegmt=True
            )
        except Exception:
            pub = now
        title = it.get("title_ko") or it["title"]
        desc = (it.get("one_liner", "") + f" — {it['journal']} ({it['year']}). 원문: " + it["url"]).strip()
        entries.append(f"""    <item>
      <title>{escape(title)}</title>
      <description>{escape(desc)}</description>
      <link>{escape(page_url)}</link>
      <guid isPermaLink="false">{escape(it['id'])}</guid>
      <pubDate>{pub}</pubDate>
      <enclosure url="{escape(audio_url)}" length="{mp3.stat().st_size}" type="audio/mpeg"/>
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(cfg['site_title'])}</title>
    <link>{escape(base or './')}</link>
    <language>ko</language>
    <description>JITAI · 웨어러블 · mHealth · 당뇨 · 비만 · 운동 분야 최신 논문을 한국어 라디오로 듣는 자동 브리핑</description>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:category text="Science"/>
{chr(10).join(entries)}
  </channel>
</rss>
"""
    (DOCS / "feed.xml").write_text(feed, encoding="utf-8")


def main():
    cfg = load_config()
    db = json.loads((DATA / "papers.json").read_text(encoding="utf-8"))
    DOCS.mkdir(exist_ok=True)
    items = build_app_data(db)
    (DOCS / "app-data.json").write_text(
        json.dumps({"generated": time.strftime("%Y-%m-%d %H:%M"), "papers": items},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    build_feed(cfg, items)
    ready = sum(1 for i in items if i["has_audio"])
    print(f"[site] 논문 {len(items)}건 (오디오 {ready}건) → docs/app-data.json, docs/feed.xml")


if __name__ == "__main__":
    main()
