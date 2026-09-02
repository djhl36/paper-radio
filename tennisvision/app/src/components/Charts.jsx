import React from 'react'
import { COURT_LINES, MAP, toMap, HALF_LENGTH, DOUBLES_HALF_W } from '../lib/court.js'

// ---------- 레이더 (플레이스타일 10축) ----------
export function Radar({ vector, labels, compare = null, size = 260 }) {
  const keys = Object.keys(labels)
  const n = keys.length
  if (!n) return null
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 34

  const pt = (i, v) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2
    const rr = (Math.max(0, Math.min(100, v)) / 100) * r
    return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)]
  }
  const poly = (vec) => keys.map((k, i) => pt(i, vec?.[k] ?? 50).join(',')).join(' ')

  return (
    <svg className="chart" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="플레이스타일 레이더">
      {[25, 50, 75, 100].map((lvl) => (
        <polygon key={lvl} points={keys.map((_, i) => pt(i, lvl).join(',')).join(' ')}
          fill="none" stroke="#263355" strokeWidth="1" />
      ))}
      {keys.map((k, i) => {
        const [x, y] = pt(i, 100)
        return <line key={k} x1={cx} y1={cy} x2={x} y2={y} stroke="#263355" strokeWidth="1" />
      })}
      {compare && (
        <polygon points={poly(compare)} fill="rgba(56,189,248,0.16)" stroke="#38bdf8" strokeWidth="1.5" />
      )}
      <polygon points={poly(vector)} fill="rgba(214,242,74,0.22)" stroke="#d6f24a" strokeWidth="2" />
      {keys.map((k, i) => {
        const a = (Math.PI * 2 * i) / n - Math.PI / 2
        const lx = cx + (r + 20) * Math.cos(a)
        const ly = cy + (r + 20) * Math.sin(a)
        return (
          <text key={k} x={lx} y={ly} fontSize="9.5" fill="#92a1c0"
            textAnchor={Math.abs(Math.cos(a)) < 0.3 ? 'middle' : (Math.cos(a) > 0 ? 'start' : 'end')}
            dominantBaseline="middle">
            {labels[k]}
          </text>
        )
      })}
    </svg>
  )
}

// ---------- 코트 미니맵 + 바운스 산점도 ----------
export function CourtMap({
  bounces = [], shots = [], highlight = null, height = MAP.h, showHalf = null, children,
}) {
  const map = { ...MAP, h: height }
  const colorOf = (b) => {
    if (b.result === 'winner' || b.result === 'ace') return '#4ade80'
    if (b.result && b.result.endsWith('error')) return '#fb7185'
    if (b.kind === 'out' || b.kind === 'fault') return '#fb7185'
    if (b.tooClose) return '#fbbf24'
    return '#38bdf8'
  }
  return (
    <svg className="chart" viewBox={`0 0 ${map.w} ${map.h}`} style={{ maxHeight: height }}>
      <rect x="0" y="0" width={map.w} height={map.h} rx="10" fill="#132340" />
      {showHalf && (
        <rect
          x={map.pad}
          y={showHalf === 'far' ? map.pad : map.h / 2}
          width={map.w - map.pad * 2}
          height={(map.h - map.pad * 2) / 2}
          fill="rgba(56,189,248,0.06)"
        />
      )}
      {COURT_LINES.map(([x1, y1, x2, y2], i) => {
        const a = toMap(x1, y1, map)
        const b = toMap(x2, y2, map)
        return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#7f95c4" strokeWidth="1" />
      })}
      {/* 네트 */}
      <line
        x1={toMap(-DOUBLES_HALF_W, 0, map)[0]} y1={toMap(0, 0, map)[1]}
        x2={toMap(DOUBLES_HALF_W, 0, map)[0]} y2={toMap(0, 0, map)[1]}
        stroke="#e8edf7" strokeWidth="2" strokeDasharray="3 3"
      />
      {shots.map((s, i) => {
        if (!s.contact || !s.bounce) return null
        const a = toMap(s.contact[0], s.contact[1], map)
        const b = toMap(s.bounce[0], s.bounce[1], map)
        return <line key={`s${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
          stroke="rgba(232,237,247,0.22)" strokeWidth="1" />
      })}
      {bounces.map((b, i) => {
        const [x, y] = toMap(b.x, b.y, map)
        const isHi = highlight != null && highlight === i
        return (
          <circle key={i} cx={x} cy={y} r={isHi ? 6 : 3.4} fill={colorOf(b)}
            opacity={isHi ? 1 : 0.82} stroke={isHi ? '#fff' : 'none'} strokeWidth="1.5" />
        )
      })}
      {children}
    </svg>
  )
}

// ---------- 가로 막대 ----------
export function BarList({ items, max = null, unit = '', color = '#38bdf8' }) {
  const hi = max ?? Math.max(1, ...items.map((i) => i.value))
  return (
    <div className="list" style={{ gap: 7 }}>
      {items.map((it) => (
        <div key={it.label}>
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 3 }}>
            <span className="small">{it.label}</span>
            <span className="small mono muted">{it.display ?? `${it.value}${unit}`}</span>
          </div>
          <div className="bar">
            <i style={{ width: `${Math.min(100, (it.value / hi) * 100)}%`, background: it.color || color }} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------- 도넛(비율) ----------
export function Donut({ value, label, sub, color = '#d6f24a', size = 92 }) {
  const r = size / 2 - 7
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(1, value))
  return (
    <div className="center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#263355" strokeWidth="7" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="7"
          strokeDasharray={`${c * pct} ${c}`} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="49%" textAnchor="middle" dominantBaseline="middle"
          fontSize="17" fontWeight="700" fill="#e8edf7">
          {Math.round(pct * 100)}%
        </text>
      </svg>
      <div className="small" style={{ marginTop: 2 }}>{label}</div>
      {sub && <div className="small muted">{sub}</div>}
    </div>
  )
}

// ---------- 랠리 길이 분포 ----------
export function RallyBuckets({ buckets }) {
  const entries = Object.entries(buckets || {})
  if (!entries.length) return <div className="empty">데이터 없음</div>
  return (
    <div className="grid3">
      {entries.map(([label, v]) => (
        <div key={label} className="card tight center">
          <div className="small muted">{label}구</div>
          <div className="big" style={{ fontSize: 20 }}>
            {v.pct == null ? '—' : `${Math.round(v.pct * 100)}%`}
          </div>
          <div className="small muted">{v.won}/{v.points}</div>
        </div>
      ))}
    </div>
  )
}
