import React from "react";
import { SLOT_MIN, blockSummary } from "../engine/blocks.js";

const pad = (n) => String(n).padStart(2, "0");

/**
 * 하루 블록 격자. 한 줄이 1시간(30분 × 2칸).
 * 빈 칸을 누르면 그 시간대로 기록을 추가하고, 찬 칸을 누르면 그 기록을 연다.
 */
export default function BlockTimeline({ slots, onEmpty, onLog, onPlan }) {
  if (!slots.length) return null;
  const sum = blockSummary(slots);
  const perRow = Math.max(1, Math.round(60 / SLOT_MIN));
  const rows = [];
  for (let i = 0; i < slots.length; i += perRow) rows.push(slots.slice(i, i + perRow));

  return (
    <>
      <div className="row between sub" style={{ marginBottom: 8 }}>
        <span>기록된 시간 {Math.round(sum.filledMin / 60 * 10) / 10}h · 빈 시간 {Math.round(sum.emptyMin / 60 * 10) / 10}h</span>
        <span className={sum.coverage >= 60 ? "" : "dim"}>채움 {sum.coverage}%</span>
      </div>
      <div className="blocks">
        {rows.map((row, i) => (
          <div className="brow" key={i}>
            <span className="btime">{pad(new Date(row[0].start).getHours())}</span>
            {row.map((s) => {
              const cls = [
                "bcell",
                s.log ? "done" : s.plan ? "plan" : "empty",
                s.now ? "current" : "",
                s.first ? "first" : "",
                s.last ? "last" : ""
              ].join(" ");
              const label = s.first && s.act ? s.act.name : "";
              return (
                <button
                  className={cls}
                  key={s.start}
                  title={`${pad(new Date(s.start).getHours())}:${pad(new Date(s.start).getMinutes())} ${s.act ? "· " + s.act.name : ""}`}
                  onClick={() => (s.log ? onLog?.(s.log) : s.plan ? onPlan?.(s.plan) : onEmpty?.(s))}
                >
                  {s.act ? <span className="be">{s.first ? s.act.emoji : ""}</span> : null}
                  {label ? <span className="bl">{label}</span> : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="row wrap sub" style={{ gap: 10, marginTop: 8, fontSize: 11.5 }}>
        <span><i className="key done" /> 기록됨</span>
        <span><i className="key planb" /> 계획</span>
        <span><i className="key emptyb" /> 빈 칸 — 눌러서 채우기</span>
      </div>
    </>
  );
}
