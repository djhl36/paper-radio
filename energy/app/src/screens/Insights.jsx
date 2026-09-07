import React, { useMemo, useState } from "react";
import { Empty, josa } from "../components/ui.jsx";
import { activityStats, bestDuration, dailyLoad, dayHistory } from "../engine/learn.js";
import {
  bedBands, bedMinutes, drainOrder, patternFindings, sleepBands, topActivities, weekdayStats
} from "../engine/patterns.js";
import { useApp } from "../store.js";

function BandTable({ title, rows, unit }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  return (
    <div className="card">
      <h2>{title}</h2>
      <table className="t">
        <thead><tr><th>{unit}</th><th>일수</th><th>HP</th><th>MP</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} style={r.n === 0 ? { opacity: 0.35 } : undefined}>
              <td>
                {r.label}
                <span className="bandbar" style={{ width: `${(r.n / max) * 46}px` }} />
              </td>
              <td>{r.n}</td>
              <td style={{ color: "var(--hp)" }}>{r.n ? r.hp : "–"}</td>
              <td style={{ color: "var(--mp)" }}>{r.n ? r.mp : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Insights() {
  const { data, activities } = useApp();
  const logs = data.logs;
  const [tab, setTab] = useState("pattern");

  const hist = useMemo(() => dayHistory(data.days), [data.days]);
  const histE = hist.filter((r) => r.hp != null);
  const findings = useMemo(() => patternFindings(hist), [hist]);
  const sb = useMemo(() => sleepBands(hist), [hist]);
  const bb = useMemo(() => bedBands(hist), [hist]);
  const wd = useMemo(() => weekdayStats(hist), [hist]);
  const top = useMemo(() => topActivities(hist, 12), [hist]);
  const drain = useMemo(() => drainOrder(hist), [hist]);

  const stats = useMemo(() => activityStats(logs, activities, data.learn).filter((s) => s.n > 0), [logs, activities, data.learn]);
  const days14 = useMemo(() => dailyLoad(logs, 14), [logs]);
  const maxLoad = Math.max(30, ...days14.map((d) => d.hp + d.mp));

  const logFindings = useMemo(() => {
    const out = [];
    for (const s of stats) {
      const k = s.k;
      if (s.n >= 3 && Math.abs(k.kHp - 1) >= 0.15)
        out.push(`${s.act.emoji} ${s.act.name}${josa(s.act.name)} 기본값보다 몸 부하가 약 ${Math.round(Math.abs(k.kHp - 1) * 100)}% ${k.kHp > 1 ? "높습니다" : "낮습니다"}.`);
      if (s.n >= 3 && Math.abs(k.kMp - 1) >= 0.15)
        out.push(`${s.act.emoji} ${s.act.name}의 머리 부하는 기본값보다 약 ${Math.round(Math.abs(k.kMp - 1) * 100)}% ${k.kMp > 1 ? "높습니다" : "낮습니다"}.`);
      const bd = bestDuration(logs, s.act.id);
      if (bd) out.push(`${s.act.emoji} ${s.act.name}의 효율이 가장 좋은 구간은 ${bd.best.label}입니다.`);
    }
    return out;
  }, [stats, logs]);

  const empty = !histE.length && !logs.length;

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>📊 인사이트</h1>
          <div className="sub">하루 기록 {histE.length}일 · 활동 기록 {logs.length}건</div>
        </div>
      </div>

      {empty ? (
        <div className="card"><Empty>활동을 몇 번 기록하면 여기에 당신만의 패턴이 쌓입니다.</Empty></div>
      ) : (
        <>
          <div style={{ marginBottom: 12 }}>
            <div className="seg">
              <button className={tab === "pattern" ? "on" : ""} onClick={() => setTab("pattern")}>나의 패턴</button>
              <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>기록 추이</button>
              <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}>활동별</button>
            </div>
          </div>

          {tab === "pattern" ? (
            <>
              {findings.length ? (
                <div className="card">
                  <h2>기록에서 확인된 것 ({histE.length}일)</h2>
                  <div className="list">
                    {findings.map((f, i) => (
                      <div className="item" key={i} style={{ alignItems: "flex-start" }}>
                        <span className="emoji">{f.icon}</span>
                        <span className="body" style={{ fontSize: 13.5, lineHeight: 1.55 }}>
                          {f.text.split("**").map((part, j) => (j % 2 ? <strong key={j}>{part}</strong> : part))}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="card"><Empty>패턴을 말하려면 하루 기록이 10일 이상 필요합니다.</Empty></div>
              )}

              <BandTable title="수면 시간대별 아침 상태" rows={sb} unit="수면" />
              <BandTable title="취침 시각대별 아침 상태" rows={bb} unit="취침" />

              <div className="card">
                <h2>몸 vs 머리 — 무엇이 먼저 비는가</h2>
                <div className="row between">
                  <div>
                    <div className="sub">머리가 먼저 (MP &lt; HP−10)</div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: "var(--mp)" }}>{drain.mpFirst}일</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="sub">몸이 먼저 (HP &lt; MP−10)</div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: "var(--hp)" }}>{drain.hpFirst}일</div>
                  </div>
                </div>
                <div className="sub mt">평균 HP−MP 격차 {drain.gap} · 전체 {drain.n}일</div>
              </div>

              <div className="card">
                <h2>요일별 아침 상태</h2>
                <div className="hist">
                  {wd.map((w) => (
                    <div className="hcol" key={w.name} title={`${w.name} · ${w.n}일 · HP ${w.hp} / MP ${w.mp}`}>
                      <span className="hen">
                        <i className="h" style={{ height: `${w.hp ?? 0}%` }} />
                        <i className="m" style={{ height: `${w.mp ?? 0}%` }} />
                      </span>
                      <span className="hx">{w.name}</span>
                    </div>
                  ))}
                </div>
                <div className="sub mt">초록 HP · 파랑 MP 평균. 표본이 적은 요일은 참고만 하세요.</div>
              </div>

              <div className="card">
                <h2>가장 자주 한 활동</h2>
                <div className="row wrap" style={{ gap: 6 }}>
                  {top.map((t) => (
                    <span className="chip sm" key={t.name}>{t.name} <span className="dim">{t.n}</span></span>
                  ))}
                </div>
              </div>
            </>
          ) : null}

          {tab === "history" ? (
            <>
              <div className="card">
                <h2>아침 에너지 · 수면{hist.length ? ` (${hist[0].key.slice(5)} ~ ${hist[hist.length - 1].key.slice(5)})` : ""}</h2>
                <div className="hist">
                  {hist.map((r, i) => (
                    <div className={`hcol${r.flags.includes("sick") ? " sick" : ""}`} key={r.key}
                         title={`${r.key} · HP ${r.hp ?? "-"} / MP ${r.mp ?? "-"} · 수면 ${r.sleepHours ?? "-"}h${r.bed ? ` (${r.bed}~${r.wake})` : ""}${r.nap ? ` · 낮잠 ${r.nap}h` : ""}${r.activities.length ? `\n${r.activities.join(", ")}` : ""}${r.note ? `\n${r.note}` : ""}`}>
                      <span className="hen">
                        <i className="h" style={{ height: `${r.hp ?? 0}%` }} />
                        <i className="m" style={{ height: `${r.mp ?? 0}%` }} />
                      </span>
                      <span className="hsl">
                        <i className={r.sleepHours != null && r.sleepHours < 6 ? "short" : ""}
                           style={{ height: `${Math.min(100, ((r.sleepHours ?? 0) / 11) * 100)}%` }} />
                      </span>
                      <span className="hx">{i % 5 === 0 ? r.date.getDate() : ""}</span>
                    </div>
                  ))}
                </div>
                <div className="row wrap sub" style={{ gap: 10, marginTop: 10 }}>
                  <span><i className="key h" /> 아침 HP</span>
                  <span><i className="key m" /> 아침 MP</span>
                  <span><i className="key s" /> 수면(6시간 미만 주황)</span>
                </div>
              </div>

              <div className="card">
                <h2>취침 시각 흐름</h2>
                <div className="hist">
                  {hist.map((r, i) => {
                    const b = bedMinutes(r);
                    const pct = b == null ? 0 : Math.min(100, Math.max(4, ((b - 21 * 60) / (7 * 60)) * 100));
                    return (
                      <div className="hcol" key={r.key} title={r.bed ? `${r.key} · 취침 ${r.bed} · 기상 ${r.wake || "-"}` : r.key}>
                        <span className="hen">
                          <i className={b != null && b >= 25 * 60 + 30 ? "late" : "bed"} style={{ height: `${pct}%` }} />
                        </span>
                        <span className="hx">{i % 5 === 0 ? r.date.getDate() : ""}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="sub mt">막대가 높을수록 늦게 누운 날(21시 → 새벽 4시). 01:30 이후는 붉게 표시됩니다.</div>
              </div>

              {logs.length ? (
                <div className="card">
                  <h2>최근 14일 활동 소모량</h2>
                  <div className="spark">
                    {days14.map((d) => (
                      <div className="col" key={d.key} title={`${d.key} HP ${d.hp} / MP ${d.mp}`}>
                        <i className="m" style={{ height: `${(d.mp / maxLoad) * 100}%` }} />
                        <i className="h" style={{ height: `${(d.hp / maxLoad) * 100}%` }} />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {tab === "activity" ? (
            !logs.length ? (
              <div className="card">
                <Empty>
                  활동을 시작하거나 기록하면 여기에 활동별 실제 비용과 개인 계수가 쌓입니다.<br />
                  가져온 원문에는 활동별 소모량이 없어 지금은 비어 있습니다.
                </Empty>
              </div>
            ) : (
              <>
                {logFindings.length ? (
                  <div className="card">
                    <h2>활동에서 확인된 것</h2>
                    <div className="list">
                      {logFindings.slice(0, 8).map((f, i) => (
                        <div className="item" key={i} style={{ alignItems: "flex-start" }}>
                          <span className="body" style={{ fontSize: 13.5, lineHeight: 1.5 }}>{f}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="card">
                  <h2>활동별 실제 비용 (시간당)</h2>
                  <table className="t">
                    <thead><tr><th>활동</th><th>회</th><th>HP</th><th>MP</th><th>예측대비</th></tr></thead>
                    <tbody>
                      {stats.map((s) => (
                        <tr key={s.act.id}>
                          <td>{s.act.emoji} {s.act.name}</td>
                          <td>{s.n}</td>
                          <td style={{ color: "var(--hp)" }}>{s.hpPerH}</td>
                          <td style={{ color: "var(--mp)" }}>{s.mpPerH}</td>
                          <td className={s.bias?.mp > 12 || s.bias?.hp > 12 ? "" : "dim"}>
                            {s.bias?.hp != null ? `${s.bias.hp > 0 ? "+" : ""}${Math.round(s.bias.hp)}%` : "–"}
                            {" / "}
                            {s.bias?.mp != null ? `${s.bias.mp > 0 ? "+" : ""}${Math.round(s.bias.mp)}%` : "–"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {stats.filter((s) => s.act.out && bestDuration(logs, s.act.id)).map((s) => {
                  const bd = bestDuration(logs, s.act.id);
                  return (
                    <div className="card" key={s.act.id}>
                      <h2>{s.act.emoji} {s.act.name} · 지속시간별 효율</h2>
                      <table className="t">
                        <thead><tr><th>구간</th><th>회</th><th>성과</th><th>MP</th><th>효율</th></tr></thead>
                        <tbody>
                          {bd.buckets.map((b) => (
                            <tr key={b.id} style={b.id === bd.best.id ? { color: "var(--hp)" } : undefined}>
                              <td>{b.label}</td><td>{b.n}</td><td>{b.out}</td><td>{b.cost}</td><td>{b.eff}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </>
            )
          ) : null}
        </>
      )}
    </div>
  );
}
