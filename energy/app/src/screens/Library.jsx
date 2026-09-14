import React, { useMemo, useState } from "react";
import { CATEGORIES, RECOVERY_LABEL } from "../engine/activities.js";
import { activityStats } from "../engine/learn.js";
import { r1 } from "../engine/model.js";
import { Empty, Seg, Sheet, durLabel } from "../components/ui.jsx";
import { useApp, uid } from "../store.js";

const REC_OPTS = [
  { value: 0.15, label: "낮음" },
  { value: 0.45, label: "중간" },
  { value: 0.8, label: "높음" }
];

const blank = () => ({
  id: `c_${uid()}`, emoji: "⭐", name: "", cat: "work",
  hp: 2, mp: 8, phys: 2, ment: 6, soc: 2, emo: 2, rec: 0.3, dur: 60, out: false, builtin: false
});

export default function Library() {
  const { data, dispatch, activities, fit } = useApp();
  const [cat, setCat] = useState("all");
  const [edit, setEdit] = useState(null);
  const [adv, setAdv] = useState(false);

  const stats = useMemo(() => activityStats(data.logs, activities, data.learn), [data.logs, activities, data.learn]);
  const statById = Object.fromEntries(stats.map((s) => [s.act.id, s]));

  const list = activities.filter((a) => cat === "all" || a.cat === cat);
  const save = () => { dispatch({ type: "actUpsert", act: { ...edit, name: edit.name.trim() || "새 활동" } }); setEdit(null); };

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>📚 활동</h1>
          <div className="sub">{activities.length}개 · 쓸수록 내 몸에 맞게 보정됩니다</div>
        </div>
        <button className="chip sm" onClick={() => { setEdit(blank()); setAdv(false); }}>＋ 새 활동</button>
      </div>

      <div className="row wrap" style={{ gap: 6, marginBottom: 12 }}>
        <button className={`chip sm ${cat === "all" ? "on" : ""}`} onClick={() => setCat("all")}>전체</button>
        {CATEGORIES.map((c) => (
          <button key={c.id} className={`chip sm ${cat === c.id ? "on" : ""}`} onClick={() => setCat(c.id)}>{c.emoji} {c.name}</button>
        ))}
      </div>

      <div className="list">
        {list.map((a) => {
          const s = statById[a.id];
          const k = s?.k || { kHp: 1, kMp: 1, n: 0 };
          const learned = Math.abs(k.kHp - 1) > 0.08 || Math.abs(k.kMp - 1) > 0.08;
          return (
            <button className="item tap" key={a.id} onClick={() => { setEdit({ ...a }); setAdv(false); }}>
              <span className="emoji">{a.emoji}</span>
              <span className="body">
                <span className="t">{a.name}</span>
                <span className="s">
                  {durLabel(a.dur)} · 회복비용 {RECOVERY_LABEL(a.rec)}
                  {k.n ? ` · ${k.n}회 학습` : ""}
                </span>
              </span>
              <span className="cost">
                <span className="h">{r1(a.fitHp ?? a.hp * k.kHp)}</span> <span className="dim">/</span> <span className="m">{r1(a.fitMp ?? a.mp * k.kMp)}</span>
                <br />
                <span className="dim" style={{ fontSize: 11 }}>
                  {a.fitHp != null ? `측정 ${a.fitN}회` : learned ? "보정됨" : "시간당"}
                </span>
              </span>
            </button>
          );
        })}
        {!list.length ? <Empty>이 분류에는 활동이 없습니다.</Empty> : null}
      </div>

      <Sheet open={!!edit} onClose={() => setEdit(null)} title={edit?.builtin ? "활동 수정" : edit?.name ? "활동 수정" : "새 활동"}>
        {edit ? (
          <>
            <div className="row" style={{ gap: 8 }}>
              <input
                type="text" value={edit.emoji} onChange={(e) => setEdit({ ...edit, emoji: e.target.value.slice(0, 3) })}
                style={{ width: 66, textAlign: "center", fontSize: 22 }}
              />
              <input type="text" value={edit.name} placeholder="활동 이름" onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            </div>

            <label className="f">분류</label>
            <div className="row wrap" style={{ gap: 6 }}>
              {CATEGORIES.map((c) => (
                <button key={c.id} className={`chip sm ${edit.cat === c.id ? "on" : ""}`} onClick={() => setEdit({ ...edit, cat: c.id })}>
                  {c.emoji} {c.name}
                </button>
              ))}
            </div>

            <label className="f">시간당 HP 소모 <span className="dim">({edit.hp} · 음수면 회복)</span></label>
            <input type="range" min="-20" max="20" step="1" value={edit.hp} onChange={(e) => setEdit({ ...edit, hp: +e.target.value })} />
            <label className="f">시간당 MP 소모 <span className="dim">({edit.mp} · 음수면 회복)</span></label>
            <input type="range" min="-20" max="20" step="1" value={edit.mp} onChange={(e) => setEdit({ ...edit, mp: +e.target.value })} />

            <label className="f">대표 시간 <span className="dim">({durLabel(edit.dur)})</span></label>
            <input type="range" min="10" max="240" step="5" value={edit.dur} onChange={(e) => setEdit({ ...edit, dur: +e.target.value })} />

            <label className="f">회복 비용 <span className="dim">(끝난 뒤 얼마나 오래 남는가)</span></label>
            <Seg options={REC_OPTS} value={REC_OPTS.reduce((a, o) => (Math.abs(o.value - edit.rec) < Math.abs(a.value - edit.rec) ? o : a)).value}
              onChange={(v) => setEdit({ ...edit, rec: v })} />

            <label className="f">성과 기록</label>
            <button className={`chip ${edit.out ? "on" : ""}`} onClick={() => setEdit({ ...edit, out: !edit.out })}>
              {edit.out ? "✓ 끝나고 성과를 함께 기록" : "성과는 묻지 않음"}
            </button>

            <button className="chip sm" style={{ marginTop: 16 }} onClick={() => setAdv(!adv)}>
              {adv ? "▾" : "▸"} 부하 성격 (고급)
            </button>
            {adv ? (
              <>
                {[["phys", "신체"], ["ment", "인지"], ["soc", "사회"], ["emo", "감정"]].map(([k, label]) => (
                  <div key={k}>
                    <label className="f">{label} <span className="dim">({edit[k]}/10)</span></label>
                    <input type="range" min="0" max="10" value={edit[k]} onChange={(e) => setEdit({ ...edit, [k]: +e.target.value })} />
                  </div>
                ))}
              </>
            ) : null}

            {fit[edit.id]?.ok ? (
              <div className="card" style={{ marginTop: 16 }}>
                <h2>기록으로 맞춘 파라미터</h2>
                <table className="t">
                  <thead><tr><th></th><th>모델값</th><th>측정값</th><th>강도 1당</th></tr></thead>
                  <tbody>
                    <tr>
                      <td>시간당 HP</td><td className="dim">{fit[edit.id].priorHp}</td>
                      <td style={{ color: "var(--hp)" }}>{fit[edit.id].hp}</td>
                      <td>{fit[edit.id].iHp > 0 ? "+" : ""}{fit[edit.id].iHp}</td>
                    </tr>
                    <tr>
                      <td>시간당 MP</td><td className="dim">{fit[edit.id].priorMp}</td>
                      <td style={{ color: "var(--mp)" }}>{fit[edit.id].mp}</td>
                      <td>{fit[edit.id].iMp > 0 ? "+" : ""}{fit[edit.id].iMp}</td>
                    </tr>
                  </tbody>
                </table>
                <div className="sub mt">
                  기록 {fit[edit.id].n}회 · 측정값 반영 비중 {Math.round(fit[edit.id].weight * 100)}% ·
                  설명력 R² {fit[edit.id].r2Hp}/{fit[edit.id].r2Mp}
                  {fit[edit.id].iHp === 0 && fit[edit.id].iMp === 0 ? " · 강도를 거의 바꾸지 않아 강도 민감도는 추정하지 않았습니다" : ""}
                </div>
                <div className="sub" style={{ marginTop: 6, fontSize: 11.5 }}>
                  기록이 {6}회 이상 쌓이면 모델 대신 이 값으로 예측합니다. 기록을 지우면 모델값으로 돌아갑니다.
                </div>
              </div>
            ) : null}

            {data.learn[edit.id]?.n ? (
              <div className="card" style={{ marginTop: 16 }}>
                <h2>학습된 개인 계수</h2>
                <div className="sub">
                  {data.learn[edit.id].n}회 기록 기준 · HP ×{data.learn[edit.id].kHp.toFixed(2)} · MP ×{data.learn[edit.id].kMp.toFixed(2)}
                </div>
                <button className="btn ghost block mt" onClick={() => { dispatch({ type: "actReset", id: edit.id }); setEdit(null); }}>
                  학습값 초기화
                </button>
              </div>
            ) : null}

            <div className="grid2" style={{ marginTop: 16 }}>
              {edit.builtin ? (
                <button className="btn danger" onClick={() => { dispatch({ type: "actHide", id: edit.id }); setEdit(null); }}>목록에서 숨기기</button>
              ) : (
                <button className="btn danger" onClick={() => { dispatch({ type: "actDelete", id: edit.id }); setEdit(null); }}>삭제</button>
              )}
              <button className="btn primary" onClick={save}>저장</button>
            </div>
          </>
        ) : null}
      </Sheet>

      {data.hidden.length ? (
        <div className="card" style={{ marginTop: 12 }}>
          <h2>숨긴 활동 ({data.hidden.length})</h2>
          <div className="row wrap" style={{ gap: 6 }}>
            {data.hidden.map((id) => (
              <button key={id} className="chip sm" onClick={() => dispatch({ type: "actHide", id })}>↩ {id}</button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
