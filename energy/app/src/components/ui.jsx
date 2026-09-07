import React, { useEffect } from "react";

export const hhmm = (ts) => {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export const durLabel = (m) => {
  m = Math.round(m);
  if (m < 60) return `${m}분`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}시간 ${r}분` : `${h}시간`;
};

/** 한글 받침에 맞춰 조사를 고른다 ("테니스는", "수업은") */
export function josa(word, pair = "은는") {
  const [withJong, without] = [pair[0], pair[1]];
  const c = String(word || "").trim().slice(-1).charCodeAt(0);
  if (Number.isNaN(c) || c < 0xac00 || c > 0xd7a3) return without;
  return (c - 0xac00) % 28 ? withJong : without;
}

export const signed = (v) => (v > 0 ? `-${Math.round(v)}` : `+${Math.round(Math.abs(v))}`);

/** HP/MP 게이지. ghost = 예상 소모 후 위치 */
export function Gauge({ kind, value, ghost, floor, label, note }) {
  const v = Math.max(0, Math.min(100, value));
  const g = ghost == null ? null : Math.max(0, Math.min(100, ghost));
  return (
    <div className={`gauge ${kind}`}>
      <div className="top">
        <span className="name">{label || kind.toUpperCase()}</span>
        <span className="val">
          {Math.round(v)}
          <small>/100</small>
          {note ? <small style={{ marginLeft: 8 }}>{note}</small> : null}
        </span>
      </div>
      <div className="bar">
        <i style={{ width: `${v}%` }} />
        {g != null && g < v ? <span className="ghost" style={{ left: `${g}%`, width: `${v - g}%` }} /> : null}
        {floor != null ? <span className="floor" style={{ left: `${floor}%` }} /> : null}
      </div>
    </div>
  );
}

export function Sheet({ open, onClose, title, children }) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);
  if (!open) return null;
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true">
        <div className="sheet-wrap">
          <div className="grab" />
          {title ? <h3>{title}</h3> : null}
          {children}
        </div>
      </div>
    </>
  );
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Feel({ scale, value, onChange }) {
  return (
    <div className="feel">
      {scale.map((s, i) => (
        <button key={i} className={value === i ? "on" : ""} onClick={() => onChange(i)}>
          <span className="e">{s.emoji}</span>
          <span className="l">{s.label}</span>
        </button>
      ))}
    </div>
  );
}

export function CostText({ hp, mp }) {
  return (
    <span>
      <span className="h">HP {signed(hp)}</span>
      <span className="dim"> · </span>
      <span className="m">MP {signed(mp)}</span>
    </span>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}
