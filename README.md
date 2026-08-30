# 🎙️ 논문 라디오 — mHealth 연구 자동 브리핑

JITAI · 웨어러블 · mHealth · 당뇨 · 비만 · 운동 분야의 최신 논문을 자동으로 수집하고,
한국어 요약과 2인 팟캐스트 오디오로 변환해 핸드폰에서 딸깍 한 번으로 듣는 시스템.

## 구조

```
mhealthcare/
├── run_pipeline.py          # 전체 파이프라인 실행 (수집→요약→오디오→빌드)
├── pipeline/
│   ├── config.json          # 저널·주제 키워드·TTS 음성 설정
│   ├── fetch_papers.py      # Europe PMC API로 논문 수집 → data/papers.json
│   ├── summarize.py         # Claude CLI로 한국어 요약+라디오 대본 생성
│   ├── make_audio.py        # edge-tts로 2인 대화 mp3 생성
│   └── build_site.py        # 웹앱 데이터 + 팟캐스트 RSS 생성
├── data/
│   ├── papers.json          # 논문 메타데이터 DB (누적)
│   └── summaries/{id}.json  # 논문별 요약+대본
└── docs/                    # 배포용 정적 사이트 (GitHub Pages 대응)
    ├── index.html           # PWA 웹앱 (목록·요약·플레이어)
    ├── feed.xml             # 팟캐스트 RSS (팟캐스트 앱 구독용)
    └── audio/{id}.mp3       # 에피소드 오디오
```

## 실행

```bash
python run_pipeline.py
```

각 단계는 이미 처리된 논문을 건너뛰므로(증분 처리) 매주 돌려도 신규 논문만 처리된다.

### 사전 조건
- `pip install edge-tts requests`
- 요약 자동화: Claude Code CLI 로그인 필요 → 터미널에서 `claude` 실행 후 `/login` (1회)

## 로컬에서 앱 보기

```bash
python -m http.server 8080 -d docs
```

→ 브라우저에서 http://localhost:8080

## 핸드폰에서 보기 (배포)

`docs/` 폴더를 GitHub Pages 등에 올리면 끝. 배포 후 `pipeline/config.json`의
`site_base_url`에 배포 URL을 넣고 다시 빌드하면 팟캐스트 RSS(`feed.xml`)의
오디오 링크가 절대경로가 되어 Apple Podcasts / 팟캐스트 앱에서 구독 가능.

핸드폰 브라우저에서 접속 → "홈 화면에 추가" 하면 앱처럼 설치됨(PWA).

## 매주 자동 실행 (Windows 작업 스케줄러)

```powershell
.\register_schedule.ps1
```

매주 월요일 오전 7시에 파이프라인이 자동 실행된다.

## 설정 변경

`pipeline/config.json`:
- `topics`: 주제별 검색 쿼리 (Europe PMC 문법)
- `journals`: 대상 저널 목록
- `lookback_days`: 수집 기간 (기본 120일)
- `max_papers_per_topic`: 주제당 최대 수집 논문 수
- `tts_voices`: TTS 음성 (edge-tts 음성 목록: `edge-tts --list-voices`)
