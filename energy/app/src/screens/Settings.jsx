import React, { useRef, useState } from "react";
import FeedbackSheet from "../components/FeedbackSheet.jsx";
import { Gauge, Sheet, durLabel, hhmm } from "../components/ui.jsx";
import { fetchICS } from "../engine/calendar.js";
import { FOOD_MODELS } from "../engine/food.js";
import { readSamsungFiles } from "../engine/samsung.js";
import { makeDemo } from "../engine/demo.js";
import { normalizeImport } from "../engine/importer.js";
import { notifyState, requestNotifyPermission } from "../engine/notify.js";
import { useApp } from "../store.js";

const REMINDERS = [10, 20, 30, 60];

export default function Settings() {
  const { data, dispatch, actById, activities, vitals, state, today } = useApp();
  const [adjust, setAdjust] = useState(false);
  const [hp, setHp] = useState(Math.round(state.hp));
  const [mp, setMp] = useState(Math.round(state.mp));
  const [logsOpen, setLogsOpen] = useState(false);
  const [report, setReport] = useState(null);
  const [notify, setNotify] = useState(notifyState());
  const [syncMsg, setSyncMsg] = useState(null);
  const [session, setSession] = useState(null);
  const [health, setHealth] = useState(null);
  const healthRef = useRef(null);
  const fileRef = useRef(null);
  const p = data.profile;

  const exportData = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `energy-optimizer-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const importData = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const { data: next, report: rep } = normalizeImport(JSON.parse(String(r.result)), activities, null);
        dispatch({ type: "replace", data: next });
        setReport(rep);
      } catch (err) {
        setReport({ error: err?.message || "파일을 읽지 못했습니다." });
      }
    };
    r.readAsText(f);
    e.target.value = "";
  };

  const seedDemo = () => {
    if (!confirm("2주치 예시 기록을 넣습니다. 기존 기록은 그대로 두고 덧붙입니다.")) return;
    const { logs, learn } = makeDemo();
    dispatch({ type: "replace", data: { ...data, logs: [...data.logs, ...logs], learn: { ...data.learn, ...learn } } });
  };

  // 삼성 헬스 "개인 데이터 다운로드" CSV 여러 개를 한 번에 읽는다
  const importHealth = async (e) => {
    const files = [...(e.target.files || [])];
    e.target.value = "";
    if (!files.length) return;
    setHealth({ busy: true });
    try {
      const read = await Promise.all(
        files.map((f) => f.text().then((text) => ({ text, name: f.name })))
      );
      const { days, sessions, counts } = readSamsungFiles(read);

      if (Object.keys(days).length) dispatch({ type: "daysMerge", patches: days });

      // 운동 세션 → 활동 기록. 이름을 못 찾으면 비슷한 활동에 붙인다.
      const fallback = activities.find((a) => a.name === "웨이트") || activities.find((a) => a.cat === "exercise");
      const logs = sessions
        .map((x) => {
          const act = (x.name && activities.find((a) => a.name === x.name)) || fallback;
          if (!act) return null;
          const pred = { hp: 0, mp: 0, debt: 0 };
          return {
            actId: act.id,
            startTs: x.startTs,
            durationMin: x.durationMin,
            intensity: x.intensity,
            pred,
            actual: { hp: 0, mp: 0 },
            ratio: { hp: 1, mp: 1 },
            output: null,
            note: `삼성 헬스${x.hr ? ` · 평균 ${x.hr}bpm` : ""}${x.calorie ? ` · ${x.calorie}kcal` : ""}`,
            fromWatch: true
          };
        })
        .filter(Boolean);
      if (logs.length) dispatch({ type: "logsAdd", logs });

      setHealth({
        ok: true,
        days: Object.keys(days).length,
        sleep: counts.sleep,
        steps: counts.steps,
        exercise: logs.length,
        skipped: counts.unknown
      });
    } catch (err) {
      setHealth({ error: err?.message || "파일을 읽지 못했습니다." });
    }
  };

  const enableNotify = async () => {
    const res = await requestNotifyPermission();
    setNotify(res);
    dispatch({ type: "calendar", patch: { notify: res === "granted" } });
  };

  const syncUrl = async () => {
    if (!data.calendar.url) return;
    setSyncMsg("불러오는 중…");
    try {
      const events = await fetchICS(data.calendar.url);
      setSyncMsg(`일정 ${events.length}건을 읽었습니다. 계획 탭 → 📥 캘린더에서 골라 담으세요.`);
      dispatch({ type: "calendar", patch: { lastSync: Date.now() } });
      sessionStorage.setItem("eo-ics-cache", JSON.stringify(events.slice(0, 200)));
    } catch (err) {
      setSyncMsg(`직접 읽지 못했습니다 (${err.message}). 구글 캘린더는 브라우저에서 바로 읽는 것을 막는 경우가 많습니다 — .ics 파일을 내려받아 계획 탭에서 가져오세요.`);
    }
  };

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>⚙️ 설정</h1>
          <div className="sub">모든 데이터는 이 기기에만 저장됩니다</div>
        </div>
      </div>

      <div className="card">
        <h2>현재 상태 보정</h2>
        {adjust ? (
          <>
            <Gauge kind="hp" value={hp} floor={p.floor} label="HP" />
            <input type="range" min="0" max="100" value={hp} onChange={(e) => setHp(+e.target.value)} />
            <Gauge kind="mp" value={mp} floor={p.floor} label="MP" />
            <input type="range" min="0" max="100" value={mp} onChange={(e) => setMp(+e.target.value)} />
            <div className="sub mt">계산값은 HP {Math.round(vitals.hp)} · MP {Math.round(vitals.mp)}. 차이는 오늘 하루만 유지됩니다.</div>
            <div className="grid2 mt">
              <button className="btn" onClick={() => setAdjust(false)}>취소</button>
              <button
                className="btn primary"
                onClick={() => {
                  dispatch({ type: "override", hp, mp, baseHp: vitals.hp, baseMp: vitals.mp, key: today, now: Date.now() });
                  setAdjust(false);
                }}
              >
                적용
              </button>
            </div>
          </>
        ) : (
          <div className="row between">
            <span className="mono">HP {Math.round(state.hp)} · MP {Math.round(state.mp)} · 지연피로 {Math.round(vitals.debt)}</span>
            <div className="row" style={{ gap: 6 }}>
              {data.override ? <button className="chip sm" onClick={() => dispatch({ type: "clearOverride" })}>보정 해제</button> : null}
              <button className="chip sm" onClick={() => { setHp(Math.round(state.hp)); setMp(Math.round(state.mp)); setAdjust(true); }}>보정</button>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>캘린더 · 알림</h2>
        <div className="sub" style={{ lineHeight: 1.6, marginBottom: 10 }}>
          계획을 <strong>.ics로 내보내면</strong> 캘린더 앱에 일정과 알림이 함께 등록됩니다(가장 확실한 방법).
          반대로 캘린더의 .ics를 계획 탭에서 가져올 수 있습니다.
        </div>
        <label className="f">일정 알림 시점</label>
        <div className="seg">
          {REMINDERS.map((m) => (
            <button key={m} className={data.calendar.reminderMin === m ? "on" : ""}
                    onClick={() => dispatch({ type: "calendar", patch: { reminderMin: m } })}>
              {m}분 전
            </button>
          ))}
        </div>

        <label className="f">앱 알림</label>
        {notify === "granted" ? (
          <button className={`chip ${data.calendar.notify ? "on" : ""}`}
                  onClick={() => dispatch({ type: "calendar", patch: { notify: !data.calendar.notify } })}>
            {data.calendar.notify ? "✓ 앱이 열려 있을 때 알림" : "앱 알림 꺼짐"}
          </button>
        ) : (
          <button className="btn block" onClick={enableNotify}>
            {notify === "denied" ? "알림이 차단되어 있습니다 (브라우저 설정에서 허용)" : "알림 권한 요청"}
          </button>
        )}
        <div className="sub mt" style={{ fontSize: 11.5 }}>
          앱 알림은 앱이 살아 있을 때만 뜹니다. 확실한 알림은 .ics 내보내기 쪽을 쓰세요.
        </div>

        <label className="f">캘린더 구독 주소 <span className="dim">(선택 · 구글 캘린더의 비공개 ICS 주소)</span></label>
        <input
          type="text" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics"
          value={data.calendar.url}
          onChange={(e) => dispatch({ type: "calendar", patch: { url: e.target.value.trim() } })}
        />
        <button className="btn block mt" onClick={syncUrl} disabled={!data.calendar.url}>주소에서 불러오기 시도</button>
        <button
          className={`chip mt ${data.calendar.autoImport ? "on" : ""}`}
          onClick={() => dispatch({ type: "calendar", patch: { autoImport: !data.calendar.autoImport, lastSync: null } })}
        >
          {data.calendar.autoImport ? "✓ 앱 열 때 자동으로 가져오기" : "자동 가져오기 꺼짐"}
        </button>
        {syncMsg ? <div className="sub mt">{syncMsg}</div> : null}
      </div>

      <div className="card">
        <h2>건강 데이터 (삼성 헬스)</h2>
        <div className="sub" style={{ lineHeight: 1.6, marginBottom: 10 }}>
          삼성 헬스는 웹에서 바로 읽을 수 있는 통로가 없습니다(워치 데이터는 안드로이드 앱만 접근 가능).
          대신 <strong>삼성 헬스 앱 → 설정 → 개인 데이터 다운로드</strong>로 받은 압축을 풀고,
          아래 파일들을 골라 주세요. 수면·걸음·운동이 한 번에 들어옵니다.
        </div>
        <div className="sub mono" style={{ fontSize: 11, marginBottom: 10 }}>
          com.samsung.shealth.sleep.*.csv<br />
          com.samsung.shealth.tracker.pedometer_day_summary.*.csv<br />
          com.samsung.shealth.exercise.*.csv
        </div>
        <button className="btn block" onClick={() => healthRef.current?.click()}>
          {health?.busy ? "읽는 중…" : "📥 삼성 헬스 CSV 가져오기"}
        </button>
        <input ref={healthRef} type="file" accept=".csv,text/csv" multiple style={{ display: "none" }} onChange={importHealth} />
        {health?.ok ? (
          <div className="sub mt" style={{ color: "var(--hp)" }}>
            일자 {health.days}일 반영 · 수면 {health.sleep}건 · 걸음 {health.steps}건 · 운동 {health.exercise}건
            {health.skipped ? ` · 알 수 없는 파일 ${health.skipped}개` : ""}
            <br />운동 기록은 강도만 심박에서 추정했습니다. 오늘 화면에서 눌러 활동과 체감을 고쳐 주세요.
          </div>
        ) : null}
        {health?.error ? <div className="sub mt" style={{ color: "var(--bad)" }}>{health.error}</div> : null}
      </div>

      <div className="card">
        <h2>AI 사진 판별</h2>
        <div className="sub" style={{ lineHeight: 1.6, marginBottom: 10 }}>
          식사 사진으로 영양을 어림잡습니다. 서버가 없어서 <strong>내 API 키로 브라우저에서 직접</strong> 부릅니다 —
          키는 이 기기에만 저장되고 Anthropic 외 어디로도 가지 않습니다.
        </div>
        <label className="f">Anthropic API 키</label>
        <input
          type="password" placeholder="sk-ant-..." value={data.ai.apiKey}
          onChange={(e) => dispatch({ type: "ai", patch: { apiKey: e.target.value.trim() } })}
        />
        <label className="f">판별 모델</label>
        <div className="seg">
          {FOOD_MODELS.map((m) => (
            <button key={m.id} className={data.ai.model === m.id ? "on" : ""}
                    onClick={() => dispatch({ type: "ai", patch: { model: m.id } })}>
              {m.label}
            </button>
          ))}
        </div>
        <div className="sub mt" style={{ fontSize: 11.5 }}>
          {FOOD_MODELS.find((m) => m.id === data.ai.model)?.hint} · 사진 한 장은 대략 1~2원 수준입니다.
        </div>
      </div>

      <div className="card">
        <h2>내 리듬</h2>
        <label className="f">목표 수면 <span className="dim">({p.sleepTarget}시간)</span></label>
        <input type="range" min="5" max="10" step="0.5" value={p.sleepTarget} onChange={(e) => dispatch({ type: "profile", patch: { sleepTarget: +e.target.value } })} />
        <label className="f">안전 예비분 <span className="dim">({p.floor} — 이 아래로 내려가면 경고)</span></label>
        <input type="range" min="0" max="45" step="5" value={p.floor} onChange={(e) => dispatch({ type: "profile", patch: { floor: +e.target.value } })} />
        <div className="grid2">
          <div>
            <label className="f">기상 {p.wakeHour}시</label>
            <input type="range" min="4" max="12" value={p.wakeHour} onChange={(e) => dispatch({ type: "profile", patch: { wakeHour: +e.target.value } })} />
          </div>
          <div>
            <label className="f">취침 {p.bedHour === 24 ? "자정" : p.bedHour > 24 ? `새벽 ${p.bedHour - 24}시` : `${p.bedHour}시`}</label>
            <input type="range" min="21" max="27" value={p.bedHour} onChange={(e) => dispatch({ type: "profile", patch: { bedHour: +e.target.value } })} />
          </div>
        </div>
      </div>

      <div className="card">
        <h2>기록 ({data.logs.length}건)</h2>
        <div className="grid2">
          <button className="btn" onClick={() => setLogsOpen(true)}>기록 보기·삭제</button>
          <button className="btn" onClick={seedDemo}>예시 데이터 넣기</button>
        </div>
      </div>

      {report ? (
        <div className={`verdict ${report.error ? "red" : "green"}`}>
          <div className="t">{report.error ? "⚠️ 가져오지 못했습니다" : "✅ 가져왔습니다"}</div>
          <div className="d">
            {report.error
              ? report.error
              : `기록 ${report.logs}건 · 계획 ${report.plan}건 · 일자 ${report.days}건 · 활동 ${report.custom}개` +
                (report.skipped ? ` · 건너뜀 ${report.skipped}건` : "")}
          </div>
          <button className="chip sm" style={{ marginTop: 10 }} onClick={() => setReport(null)}>닫기</button>
        </div>
      ) : null}

      <div className="card">
        <h2>데이터</h2>
        <div className="grid2">
          <button className="btn" onClick={exportData}>내보내기(JSON)</button>
          <button className="btn" onClick={() => fileRef.current?.click()}>가져오기</button>
        </div>
        <input ref={fileRef} type="file" accept="application/json" style={{ display: "none" }} onChange={importData} />
        <button
          className="btn danger block mt"
          onClick={() => { if (confirm("모든 기록·학습값을 지웁니다. 계속할까요?")) dispatch({ type: "reset" }); }}
        >
          전체 초기화
        </button>
      </div>

      <div className="card">
        <h2>홈 화면에 추가</h2>
        <div className="sub">
          iPhone: Safari 공유 버튼 → “홈 화면에 추가”.<br />
          Android: Chrome 메뉴 → “앱 설치”.<br />
          설치하면 주소창 없이 앱처럼 열리고, 오프라인에서도 동작합니다.
        </div>
      </div>

      <Sheet open={logsOpen} onClose={() => setLogsOpen(false)} title="기록 (눌러서 수정)">
        <div className="list">
          {[...data.logs].sort((a, b) => b.startTs - a.startTs).slice(0, 60).map((l) => {
            const a = actById[l.actId];
            if (!a) return null;
            const d = new Date(l.startTs);
            return (
              <button className="item tap" key={l.id} onClick={() => { setLogsOpen(false); setSession({ ...l, act: a, logId: l.id }); }}>
                <span className="emoji">{a.emoji}</span>
                <span className="body">
                  <span className="t">{a.name}</span>
                  <span className="s">{d.getMonth() + 1}/{d.getDate()} {hhmm(l.startTs)} · {durLabel(l.durationMin)} · 강도 {l.intensity}</span>
                </span>
                <span className="cost">
                  <span className="h">{Math.round(l.actual.hp)}</span> <span className="dim">/</span> <span className="m">{Math.round(l.actual.mp)}</span>
                </span>
              </button>
            );
          })}
          {!data.logs.length ? <div className="empty">기록이 없습니다.</div> : null}
        </div>
      </Sheet>

      <FeedbackSheet
        open={!!session}
        session={session}
        onClose={() => setSession(null)}
        onDone={(log) => dispatch({ type: "updateLog", id: session.logId, patch: log })}
        onDelete={(id) => dispatch({ type: "deleteLog", id })}
      />
    </div>
  );
}
