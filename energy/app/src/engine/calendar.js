// ── 캘린더 연동 (iCalendar / .ics) ──────────────────────────────────
// 서버가 없는 앱이라 실시간 양방향 동기화는 할 수 없다. 대신 캘린더 표준 형식으로
// 주고받는다:
//   가져오기 — 구글 캘린더의 "비공개 주소(ICS)" 또는 내려받은 .ics 파일
//   내보내기 — 계획을 .ics 로 저장 → 캘린더 앱에서 열면 일정 + N분 전 알림이 등록된다
// 알림을 캘린더에 넘기는 쪽이 브라우저 알림보다 훨씬 잘 뜬다(기기 알림이므로).

const pad = (n) => String(n).padStart(2, "0");

/** RFC5545 줄 접힘(folding) 풀기 */
function unfold(text) {
  return String(text).replace(/\r\n/g, "\n").replace(/\n[ \t]/g, "");
}

/** 20260907T183000Z · 20260907T183000 · 20260907 → ms */
function parseICSDate(value, params = "") {
  const v = String(value).trim();
  const m = v.match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$/);
  if (!m) return null;
  const [, y, mo, d, hh, mi, ss, z] = m;
  if (!hh) return { ts: new Date(+y, +mo - 1, +d, 0, 0, 0, 0).getTime(), allDay: true };
  if (z || /TZID=UTC/i.test(params)) {
    return { ts: Date.UTC(+y, +mo - 1, +d, +hh, +mi, +ss), allDay: false };
  }
  // TZID 가 붙은 로컬 시각은 기기 시간대로 읽는다 (대부분 같은 시간대의 일정)
  return { ts: new Date(+y, +mo - 1, +d, +hh, +mi, +ss).getTime(), allDay: false };
}

const unescapeText = (s) =>
  String(s).replace(/\\n/gi, " ").replace(/\\,/g, ",").replace(/\\;/g, ";").replace(/\\\\/g, "\\").trim();

/** .ics 텍스트 → 일정 배열 */
export function parseICS(text) {
  const lines = unfold(text).split("\n");
  const events = [];
  let cur = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (line === "BEGIN:VEVENT") { cur = {}; continue; }
    if (line === "END:VEVENT") {
      if (cur?.start) {
        const durationMin = cur.end ? Math.round((cur.end - cur.start) / 60000) : 60;
        events.push({
          uid: cur.uid || `${cur.start}-${cur.summary || ""}`,
          summary: cur.summary || "(제목 없음)",
          location: cur.location || null,
          start: cur.start,
          durationMin: Math.max(5, Math.min(24 * 60, durationMin)),
          allDay: !!cur.allDay,
          recurring: !!cur.rrule
        });
      }
      cur = null;
      continue;
    }
    if (!cur) continue;
    const idx = line.indexOf(":");
    if (idx < 0) continue;
    const left = line.slice(0, idx);
    const value = line.slice(idx + 1);
    const name = left.split(";")[0].toUpperCase();
    const params = left.slice(name.length);
    if (name === "SUMMARY") cur.summary = unescapeText(value);
    else if (name === "LOCATION") cur.location = unescapeText(value);
    else if (name === "UID") cur.uid = value.trim();
    else if (name === "RRULE") cur.rrule = value.trim();
    else if (name === "DTSTART") {
      const p = parseICSDate(value, params);
      if (p) { cur.start = p.ts; cur.allDay = p.allDay; }
    } else if (name === "DTEND") {
      const p = parseICSDate(value, params);
      if (p) cur.end = p.ts;
    }
  }
  return events.sort((a, b) => a.start - b.start);
}

/** 제목에서 활동 찾기 — 정확히 포함 → 토큰 겹침 순 */
export function matchActivity(summary, activities) {
  const s = String(summary).toLowerCase().replace(/\s+/g, "");
  let best = null;
  let bestScore = 0;
  for (const a of activities) {
    const name = a.name.toLowerCase().replace(/\s+/g, "");
    let score = 0;
    if (s.includes(name) || name.includes(s)) score = 0.6 + Math.min(name.length, s.length) / 40;
    else {
      const tokens = a.name.split(/[\s·,]+/).filter((t) => t.length >= 2);
      const hit = tokens.filter((t) => s.includes(t.toLowerCase())).length;
      if (hit) score = 0.3 * (hit / tokens.length);
    }
    if (score > bestScore) { bestScore = score; best = a; }
  }
  return bestScore >= 0.3 ? { act: best, score: bestScore } : null;
}

const stamp = (ts) => {
  const d = new Date(ts);
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
};

const escapeText = (s) => String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");

/**
 * 계획 → .ics. VALARM 을 넣으므로 캘린더 앱이 N분 전에 알림을 준다.
 * @param items [{act, startTs, durationMin, intensity, id, pred}]
 */
export function buildICS(items, { reminderMin = 30, calendarName = "Energy Optimizer" } = {}) {
  const now = stamp(Date.now());
  const body = items
    .map((it) => {
      const end = it.startTs + (it.durationMin || 60) * 60000;
      const cost = it.pred
        ? `\n예상 소모: HP ${Math.round(it.pred.hp)} · MP ${Math.round(it.pred.mp)}`
        : "";
      const desc = escapeText(`강도 ${it.intensity ?? 5}/10${cost}`);
      return [
        "BEGIN:VEVENT",
        `UID:eo-${it.id}@energy-optimizer`,
        `DTSTAMP:${now}`,
        `DTSTART:${stamp(it.startTs)}`,
        `DTEND:${stamp(end)}`,
        `SUMMARY:${escapeText(`${it.act.emoji} ${it.act.name}`)}`,
        `DESCRIPTION:${desc}`,
        "BEGIN:VALARM",
        `TRIGGER:-PT${Math.max(0, Math.round(reminderMin))}M`,
        "ACTION:DISPLAY",
        `DESCRIPTION:${escapeText(`${it.act.name} ${reminderMin}분 전`)}`,
        "END:VALARM",
        "END:VEVENT"
      ].join("\r\n");
    })
    .join("\r\n");

  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Energy Optimizer//KO",
    "CALSCALE:GREGORIAN",
    `X-WR-CALNAME:${escapeText(calendarName)}`,
    body,
    "END:VCALENDAR"
  ].filter(Boolean).join("\r\n");
}

export function downloadText(text, filename, type = "text/calendar") {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * 구독 URL 에서 직접 읽기. 구글의 비공개 ICS 주소는 CORS 헤더를 주지 않는 경우가
 * 많아 실패할 수 있고, 그때는 파일로 받아서 가져오면 된다.
 */
export async function fetchICS(url) {
  const target = url.replace(/^webcal:/i, "https:");
  const res = await fetch(target, { mode: "cors" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return parseICS(await res.text());
}

// ── 제목으로 활동량 추정 ─────────────────────────────────────────────
// 라이브러리 이름과 정확히 맞지 않아도, 흔한 낱말이면 어떤 종류의 부하인지는 안다.
const KEYWORDS = [
  { re: /테니스|tennis/i, names: ["테니스 레슨", "테니스 개인연습", "테니스"], intensity: 6 },
  { re: /헬스|웨이트|근력|gym|짐/i, names: ["웨이트"], intensity: 6 },
  { re: /러닝|달리기|조깅|run/i, names: ["러닝"], intensity: 6 },
  { re: /수영|swim/i, names: ["수영"], intensity: 6 },
  { re: /자전거|라이딩|cycl/i, names: ["자전거 라이딩", "Zone2 유산소"], intensity: 5 },
  { re: /등산|하이킹|hik/i, names: ["등산"], intensity: 6 },
  { re: /요가|스트레칭|필라테스/i, names: ["요가·스트레칭"], intensity: 4 },
  { re: /pt|재활|물리치료/i, names: ["PT·손목 재활"], intensity: 5 },
  { re: /수업|강의|class|lecture|특강/i, names: ["수업 듣기"], intensity: 5 },
  { re: /시험|exam|quiz/i, names: ["시험"], intensity: 8 },
  { re: /과제|레포트|리포트|assignment/i, names: ["글쓰기"], intensity: 5 },
  { re: /발표|presentation|세미나/i, names: ["발표·강의하기"], intensity: 7 },
  { re: /미팅|회의|meeting|스탠드업|sync/i, names: ["인턴십 미팅", "회의"], intensity: 5 },
  { re: /면담|상담|멘토링|교수님/i, names: ["면담·상담"], intensity: 6 },
  { re: /인턴|internship/i, names: ["인턴십 프로젝트"], intensity: 5 },
  { re: /코딩|개발|coding|dev|프로젝트/i, names: ["코딩(일반)", "인턴십 프로젝트"], intensity: 5 },
  { re: /공부|스터디|study|독서실/i, names: ["공부·문제풀이"], intensity: 5 },
  { re: /교회|예배|성경|셀모임/i, names: ["교회"], intensity: 4 },
  { re: /약속|저녁|점심|식사|모임|만남|술|dinner|lunch/i, names: ["친구 만나기"], intensity: 5 },
  { re: /병원|진료|검진|치과|clinic/i, names: ["병원·행정"], intensity: 4 },
  { re: /이동|출발|귀가|공항|기차|ktx/i, names: ["장거리 이동", "이동·통근"], intensity: 4 },
  { re: /여행|trip|travel/i, names: ["여행"], intensity: 5 },
  { re: /청소|빨래|세탁|정리/i, names: ["집안일"], intensity: 4 },
  { re: /낮잠|휴식|rest|nap/i, names: ["휴식"], intensity: 3 }
];

/**
 * 일정 제목 → 활동 + 강도 추정.
 * 1) 라이브러리 이름과 직접 매칭 → 2) 낱말 사전 → 없으면 null.
 * @returns { act, intensity, how: "name" | "keyword", score }
 */
export function guessActivity(summary, activities) {
  const direct = matchActivity(summary, activities);
  if (direct) return { act: direct.act, intensity: 5, how: "name", score: direct.score };

  for (const k of KEYWORDS) {
    if (!k.re.test(summary)) continue;
    for (const n of k.names) {
      const act = activities.find((a) => a.name === n);
      if (act) return { act, intensity: k.intensity, how: "keyword", score: 0.45 };
    }
  }
  return null;
}

/** 구글 캘린더 "일정 만들기" 링크 — 누르면 브라우저에서 바로 등록된다 */
export function googleCalendarUrl(item) {
  const end = item.startTs + (item.durationMin || 60) * 60000;
  const fmt = (ts) => stamp(ts);
  const details = [
    `강도 ${item.intensity ?? 5}/10`,
    item.pred ? `예상 소모: HP ${Math.round(item.pred.hp)} · MP ${Math.round(item.pred.mp)}` : null,
    "— Energy Optimizer"
  ].filter(Boolean).join("\n");
  const q = new URLSearchParams({
    action: "TEMPLATE",
    text: `${item.act.emoji} ${item.act.name}`,
    dates: `${fmt(item.startTs)}/${fmt(end)}`,
    details
  });
  return `https://calendar.google.com/calendar/render?${q.toString()}`;
}
