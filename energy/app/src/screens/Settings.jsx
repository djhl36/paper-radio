import React, { useRef, useState } from "react";
import { Gauge, Sheet, durLabel, hhmm } from "../components/ui.jsx";
import { makeDemo } from "../engine/demo.js";
import { normalizeImport } from "../engine/importer.js";
import { useApp } from "../store.js";

export default function Settings() {
  const { data, dispatch, actById, activities } = useApp();
  const [adjust, setAdjust] = useState(false);
  const [hp, setHp] = useState(Math.round(data.state.hp));
  const [mp, setMp] = useState(Math.round(data.state.mp));
  const [logsOpen, setLogsOpen] = useState(false);
  const [report, setReport] = useState(null);
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
        const { data: next, report: rep } = normalizeImport(JSON.parse(String(r.result)), activities, data.state);
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

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>⚙️ 설정</h1>
          <div className="sub">모든 데이터는 이 기기에만 저장됩니다</div>
        </div>
      </div>

      <div className="card">
        <h2>현재 상태 직접 보정</h2>
        {adjust ? (
          <>
            <Gauge kind="hp" value={hp} floor={p.floor} label="HP" />
            <input type="range" min="0" max="100" value={hp} onChange={(e) => setHp(+e.target.value)} />
            <Gauge kind="mp" value={mp} floor={p.floor} label="MP" />
            <input type="range" min="0" max="100" value={mp} onChange={(e) => setMp(+e.target.value)} />
            <div className="grid2 mt">
              <button className="btn" onClick={() => setAdjust(false)}>취소</button>
              <button className="btn primary" onClick={() => { dispatch({ type: "setState", hp, mp, now: Date.now() }); setAdjust(false); }}>적용</button>
            </div>
          </>
        ) : (
          <div className="row between">
            <span className="mono">HP {Math.round(data.state.hp)} · MP {Math.round(data.state.mp)} · 회복부채 {Math.round(data.state.debt || 0)}</span>
            <button className="chip sm" onClick={() => { setHp(Math.round(data.state.hp)); setMp(Math.round(data.state.mp)); setAdjust(true); }}>보정</button>
          </div>
        )}
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
            <label className="f">취침 {p.bedHour}시</label>
            <input type="range" min="19" max="26" value={p.bedHour} onChange={(e) => dispatch({ type: "profile", patch: { bedHour: +e.target.value } })} />
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
              : `기록 ${report.logs}건 · 계획 ${report.plan}건 · 일자 ${report.days}건` +
                (report.skipped ? ` · 건너뜀 ${report.skipped}건` : "") +
                (report.created.length ? ` · 새 활동 ${report.created.length}개 (${report.created.slice(0, 5).join(", ")}${report.created.length > 5 ? " 외" : ""})` : "")}
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

      <Sheet open={logsOpen} onClose={() => setLogsOpen(false)} title="기록">
        <div className="list">
          {[...data.logs].sort((a, b) => b.startTs - a.startTs).slice(0, 60).map((l) => {
            const a = actById[l.actId] || { emoji: "❓", name: l.actId };
            const d = new Date(l.startTs);
            return (
              <div className="item" key={l.id}>
                <span className="emoji">{a.emoji}</span>
                <span className="body">
                  <span className="t">{a.name}</span>
                  <span className="s">{d.getMonth() + 1}/{d.getDate()} {hhmm(l.startTs)} · {durLabel(l.durationMin)}</span>
                </span>
                <span className="cost">
                  <span className="h">{Math.round(l.actual.hp)}</span> <span className="dim">/</span> <span className="m">{Math.round(l.actual.mp)}</span>
                </span>
                <button className="chip sm" onClick={() => dispatch({ type: "deleteLog", id: l.id })}>✕</button>
              </div>
            );
          })}
          {!data.logs.length ? <div className="empty">기록이 없습니다.</div> : null}
        </div>
      </Sheet>
    </div>
  );
}
