// ── 삼성 헬스 내보내기 가져오기 ──────────────────────────────────────
// 삼성 헬스는 공개 웹 API가 없다(Health Connect 는 안드로이드 앱에서만 접근 가능).
// 대신 앱의 "개인 데이터 다운로드"가 주는 CSV 묶음을 그대로 읽는다.
//   삼성 헬스 앱 → 설정 → 개인 데이터 다운로드 → 압축 해제 → 아래 파일들을 고른다
//     com.samsung.shealth.sleep.*.csv                       수면
//     com.samsung.shealth.tracker.pedometer_day_summary.*    걸음
//     com.samsung.shealth.exercise.*.csv                     운동 세션
//
// 파일 형식: 1행 메타데이터, 2행 헤더, 3행부터 값. 버전마다 열 이름 접두사가 달라서
// 이름 끝부분으로 느슨하게 찾는다.

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** 따옴표를 고려한 CSV 한 줄 분해 */
function splitCSV(line) {
  const out = [];
  let cur = "";
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

/** "2026-09-07 01:40:00.000" 또는 epoch(ms/s) → ms */
export function parseSamsungTime(v) {
  if (v == null || v === "") return null;
  const s = String(v).trim();
  if (/^\d{10}$/.test(s)) return +s * 1000;
  if (/^\d{13}$/.test(s)) return +s;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)).getTime();
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

/** 열 이름 끝부분으로 찾기 (com.samsung.health.sleep.start_time → start_time) */
const findCol = (header, ...names) => {
  for (const n of names) {
    const i = header.findIndex((h) => h === n || h.endsWith(`.${n}`));
    if (i >= 0) return i;
  }
  return -1;
};

/** 파일 한 개 파싱 → { kind, rows } */
export function parseSamsungCSV(text, filename = "") {
  const lines = String(text).replace(/\r/g, "").split("\n").filter((l) => l.trim() !== "");
  if (!lines.length) return { kind: "unknown", rows: [] };

  // 헤더는 보통 2행. 열 이름처럼 보이는 첫 줄을 찾는다.
  let headerIdx = lines.findIndex((l) => /start_time|day_time|com\.samsung\.health/.test(l) && l.includes(","));
  if (headerIdx < 0) headerIdx = 1;
  const header = splitCSV(lines[headerIdx]).map((h) => h.trim());
  const body = lines.slice(headerIdx + 1).map(splitCSV);

  const name = `${filename} ${lines[0]}`.toLowerCase();
  const kind = /sleep/.test(name) ? "sleep"
    : /pedometer|step/.test(name) ? "steps"
    : /exercise/.test(name) ? "exercise"
    : "unknown";

  return { kind, header, rows: body };
}

// 삼성 헬스 운동 코드 → 활동 이름. 확실한 것만 넣고 나머지는 일반 운동으로 떨어뜨린다.
const EXERCISE_TYPES = {
  1001: "산책", 1002: "러닝", 11007: "자전거 라이딩", 13001: "등산", 14001: "수영",
  15006: "웨이트", 15007: "웨이트", 9002: "테니스 개인연습"
};

const hrToIntensity = (hr) => (hr ? clamp(Math.round(((hr - 60) / 130) * 9 + 1), 1, 10) : 5);

/**
 * 파일 여러 개를 한 번에 해석한다.
 * @returns { days: {key: patch}, sessions: [{name, startTs, durationMin, intensity, calorie, hr}], counts }
 */
export function readSamsungFiles(files) {
  const days = {};
  const sessions = [];
  const counts = { sleep: 0, steps: 0, exercise: 0, unknown: 0 };

  const dayKeyOf = (ts) => {
    const d = new Date(ts);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const hhmm = (ts) => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  for (const { text, name } of files) {
    const { kind, header, rows } = parseSamsungCSV(text, name);
    if (kind === "unknown" || !header) { counts.unknown++; continue; }

    if (kind === "sleep") {
      const si = findCol(header, "start_time");
      const ei = findCol(header, "end_time");
      if (si < 0 || ei < 0) { counts.unknown++; continue; }
      for (const r of rows) {
        const s = parseSamsungTime(r[si]);
        const e = parseSamsungTime(r[ei]);
        if (!s || !e || e <= s) continue;
        // 기상 시각이 속한 날을 그날로 본다 (전날 밤 → 오늘 아침)
        const key = dayKeyOf(e);
        const minutes = Math.round((e - s) / 60000);
        const prev = days[key] || {};
        // 같은 날 여러 구간이면 합산하고, 가장 이른 취침·가장 늦은 기상을 쓴다
        days[key] = {
          ...prev,
          bed: prev.bedTs && prev.bedTs < s ? prev.bed : hhmm(s),
          bedTs: prev.bedTs && prev.bedTs < s ? prev.bedTs : s,
          wake: prev.wakeTs && prev.wakeTs > e ? prev.wake : hhmm(e),
          wakeTs: prev.wakeTs && prev.wakeTs > e ? prev.wakeTs : e,
          sleepHours: Math.round(((prev.sleepHours || 0) + minutes / 60) * 10) / 10,
          source: "samsung"
        };
        counts.sleep++;
      }
    } else if (kind === "steps") {
      const di = findCol(header, "day_time", "create_time", "start_time");
      const ci = findCol(header, "step_count", "count", "total_step");
      if (di < 0 || ci < 0) { counts.unknown++; continue; }
      for (const r of rows) {
        const t = parseSamsungTime(r[di]);
        const n = Number(r[ci]);
        if (!t || !Number.isFinite(n)) continue;
        const key = dayKeyOf(t);
        days[key] = { ...(days[key] || {}), steps: Math.max(days[key]?.steps || 0, Math.round(n)), source: "samsung" };
        counts.steps++;
      }
    } else if (kind === "exercise") {
      const si = findCol(header, "start_time");
      const dui = findCol(header, "duration");
      const ti = findCol(header, "exercise_type");
      const hi = findCol(header, "mean_heart_rate", "heart_rate");
      const ki = findCol(header, "calorie", "calories");
      if (si < 0) { counts.unknown++; continue; }
      for (const r of rows) {
        const s = parseSamsungTime(r[si]);
        const durMs = dui >= 0 ? Number(r[dui]) : NaN;
        if (!s || !Number.isFinite(durMs) || durMs < 60000) continue;
        const type = ti >= 0 ? Number(r[ti]) : null;
        const hr = hi >= 0 ? Number(r[hi]) : null;
        sessions.push({
          name: EXERCISE_TYPES[type] || null,
          type,
          startTs: s,
          durationMin: Math.round(durMs / 60000),
          intensity: hrToIntensity(Number.isFinite(hr) ? hr : null),
          hr: Number.isFinite(hr) ? Math.round(hr) : null,
          calorie: ki >= 0 && Number.isFinite(Number(r[ki])) ? Math.round(Number(r[ki])) : null
        });
        counts.exercise++;
      }
    }
  }

  // 내부용 임시 필드 정리
  for (const k of Object.keys(days)) {
    delete days[k].bedTs;
    delete days[k].wakeTs;
  }
  return { days, sessions, counts };
}
