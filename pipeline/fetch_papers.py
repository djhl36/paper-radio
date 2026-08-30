# -*- coding: utf-8 -*-
"""Europe PMC에서 관심 주제 논문을 수집해 data/papers.json에 누적 저장한다."""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def load_config():
    return json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))


def load_db():
    p = DATA / "papers.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_db(db):
    DATA.mkdir(exist_ok=True)
    (DATA / "papers.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def first_affiliation(result):
    for author in (result.get("authorList") or {}).get("author", []):
        for aff in (author.get("authorAffiliationDetailsList") or {}).get(
            "authorAffiliation", []
        ):
            text = aff.get("affiliation", "")
            if text:
                # 기관명만 남기고 주소/이메일 꼬리는 정리
                text = re.sub(r"[;,]?\s*\S+@\S+\.?", "", text).strip().rstrip(".,;")
                return text
    return ""


def make_id(result):
    doi = result.get("doi")
    if doi:
        return "doi-" + re.sub(r"[^a-zA-Z0-9]+", "-", doi).strip("-").lower()
    return (result.get("source", "x") + "-" + result.get("id", "unknown")).lower()


def search_topic(cfg, topic, query, since):
    journal_clause = " OR ".join(f'JOURNAL:"{j}"' for j in cfg["journals"])
    full_query = (
        f"({query}) AND ({journal_clause}) "
        f"AND FIRST_PDATE:[{since} TO {date.today().isoformat()}] "
        f"AND HAS_ABSTRACT:y"
    )
    params = {
        "query": full_query,
        "format": "json",
        "resultType": "core",
        "pageSize": cfg["max_papers_per_topic"],
        "sort": "P_PDATE_D desc",
    }
    resp = requests.get(EPMC, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json().get("resultList", {}).get("result", [])


def main():
    cfg = load_config()
    db = load_db()
    since = (date.today() - timedelta(days=cfg["lookback_days"])).isoformat()
    added = 0

    for topic, query in cfg["topics"].items():
        try:
            results = search_topic(cfg, topic, query, since)
        except Exception as e:
            print(f"[fetch] {topic} 검색 실패: {e}", file=sys.stderr)
            continue
        for r in results:
            pid = make_id(r)
            if pid in db:
                if topic not in db[pid]["topics"]:
                    db[pid]["topics"].append(topic)
                continue
            doi = r.get("doi", "")
            db[pid] = {
                "id": pid,
                "title": r.get("title", "").rstrip("."),
                "year": r.get("pubYear", ""),
                "journal": r.get("journalTitle")
                or (r.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                "authors": r.get("authorString", ""),
                "affiliation": first_affiliation(r),
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else r.get("fullTextUrlList", {}),
                "pub_date": r.get("firstPublicationDate", ""),
                "abstract": re.sub(r"<[^>]+>", " ", r.get("abstractText", "")).strip(),
                "topics": [topic],
                "status": "new",
            }
            added += 1
        print(f"[fetch] {topic}: {len(results)}건 검색됨")

    save_db(db)
    print(f"[fetch] 신규 {added}건 추가, 총 {len(db)}건")


if __name__ == "__main__":
    main()
