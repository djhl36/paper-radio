import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { navigate } from '../App.jsx'

const STYLE_OPTS = [
  ['balanced', '적당히 다른 스타일 (추천)'],
  ['similar', '비슷한 스타일'],
  ['contrast', '상반된 스타일'],
]
const PART_KO = {
  competitiveness: '실력 균형', availability: '시간대', proximity: '거리',
  style: '스타일 궁합', novelty: '새로움',
}

export default function Matchmaking({ ctx }) {
  const { me } = ctx
  const [tab, setTab] = useState('suggest')
  const [style, setStyle] = useState('balanced')
  const [data, setData] = useState({ candidates: [], weights: {} })
  const [requests, setRequests] = useState([])
  const [board, setBoard] = useState([])
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(null)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    if (!me?.id) return
    const [s, r, l] = await Promise.all([
      api.suggestions(me.id, style, 12),
      api.requests(),
      api.ladder(30),
    ])
    setData(s)
    setRequests(r)
    setBoard(l)
  }, [me?.id, style])
  useEffect(() => { load() }, [load])

  const runMatch = async () => {
    setBusy(true)
    try {
      const r = await api.runMatchmaking()
      setMsg(`${r.matched}쌍이 매칭되었습니다.`)
      await load()
    } finally { setBusy(false) }
  }

  if (!me) return <div className="page"><div className="empty">선수를 선택하세요.</div></div>

  return (
    <div className="page">
      <div className="tabs">
        {[['suggest', '추천 상대'], ['queue', '매칭 큐'], ['ladder', '랭킹']].map(([k, l]) => (
          <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {msg && <div className="banner">{msg}</div>}

      {tab === 'suggest' && (
        <>
          <div className="card tight">
            <label className="field">
              스타일 선호
              <select value={style} onChange={(e) => setStyle(e.target.value)}>
                {STYLE_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <div className="small muted" style={{ marginTop: 8 }}>
              추천 점수 = {Object.entries(data.weights || {})
                .map(([k, v]) => `${PART_KO[k] || k} ${Math.round(v * 100)}%`).join(' + ')}
            </div>
          </div>

          <div className="list">
            {data.candidates.map((c) => (
              <div key={c.playerId} className="card tight">
                <div className="row" onClick={() => setExpanded(expanded === c.playerId ? null : c.playerId)}
                  style={{ cursor: 'pointer' }}>
                  <div style={{ flex: 1 }}>
                    <div className="title">
                      {c.name}
                      <span className="muted small"> NTRP {c.ntrp} · {c.archetype}</span>
                    </div>
                    <div className="sub">{c.reasons.join(' · ') || c.predicted}</div>
                  </div>
                  <span className="pill accent">{Math.round(c.score * 100)}</span>
                </div>

                {expanded === c.playerId && (
                  <div style={{ marginTop: 10 }}>
                    <div className="list" style={{ gap: 6 }}>
                      {Object.entries(c.parts).map(([k, v]) => (
                        <div key={k}>
                          <div className="row" style={{ justifyContent: 'space-between' }}>
                            <span className="small">{PART_KO[k] || k}</span>
                            <span className="small mono muted">{Math.round(v * 100)}</span>
                          </div>
                          <div className="bar"><i style={{ width: `${Math.round(v * 100)}%` }} /></div>
                        </div>
                      ))}
                    </div>
                    <div className="small muted" style={{ marginTop: 8 }}>
                      {c.predicted}
                      {c.distanceKm != null && ` · ${c.distanceKm}km`}
                      {c.overlapHours > 0 && ` · 시간 겹침 ${c.overlapHours}h`}
                      {c.playedBefore > 0 && ` · 최근 ${c.playedBefore}회 대결`}
                    </div>
                    {c.matchupNote && <div className="small" style={{ marginTop: 4 }}>🎾 {c.matchupNote}</div>}
                    <div className="row" style={{ marginTop: 8, gap: 6 }}>
                      <button className="btn sm" onClick={() => navigate(`profile/${c.playerId}`)}>프로필</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {tab === 'queue' && (
        <>
          <RequestForm me={me} onDone={load} />
          <div className="card">
            <div className="row">
              <h3 style={{ margin: 0 }}>열린 매칭 요청 {requests.length}건</h3>
              <span className="spacer" />
              <button className="btn sm primary" onClick={runMatch} disabled={busy}>
                {busy ? '매칭 중…' : '자동 매칭 실행'}
              </button>
            </div>
            <div className="list" style={{ marginTop: 10 }}>
              {requests.map((r) => (
                <div key={r.id} className="item" style={{ cursor: 'default' }}>
                  <div style={{ flex: 1 }}>
                    <div className="title">{r.playerName}</div>
                    <div className="sub">
                      {fmtWindow(r.windowStart, r.windowEnd)} · {r.court || '코트 미정'} · {r.format}
                    </div>
                    {r.note && <div className="sub">“{r.note}”</div>}
                  </div>
                  {r.playerId === me.id && (
                    <button className="btn sm danger"
                      onClick={async () => { await api.cancelRequest(r.id); load() }}>취소</button>
                  )}
                </div>
              ))}
              {requests.length === 0 && <div className="empty">열린 요청이 없습니다.</div>}
            </div>
          </div>
        </>
      )}

      {tab === 'ladder' && (
        <div className="list">
          {board.map((p) => (
            <button key={p.playerId} className="item" onClick={() => navigate(`profile/${p.playerId}`)}>
              <div className="rank">{p.rank}</div>
              <div style={{ flex: 1 }}>
                <div className="title">{p.name} {p.playerId === me.id && <span className="pill accent">나</span>}</div>
                <div className="sub">
                  {p.archetype} · {p.wins}승 {p.losses}패 · {p.homeCourt || '—'}
                </div>
              </div>
              <div className="center">
                <div className="mono">{p.rating}</div>
                <div className="small muted">NTRP {p.ntrp}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function fmtWindow(a, b) {
  const s = new Date(a)
  const e = new Date(b)
  const d = s.toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short' })
  const t = (x) => x.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${d} ${t(s)}~${t(e)}`
}

function RequestForm({ me, onDone }) {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const defDay = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate() + 1)}`
  const [day, setDay] = useState(defDay)
  const [from, setFrom] = useState('18:00')
  const [to, setTo] = useState('21:00')
  const [court, setCourt] = useState(me.homeCourt || '')
  const [format, setFormat] = useState('one_set')
  const [style, setStyle] = useState('balanced')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api.createRequest({
        playerId: me.id,
        windowStart: new Date(`${day}T${from}:00`).toISOString(),
        windowEnd: new Date(`${day}T${to}:00`).toISOString(),
        court, format, stylePreference: style, note,
      })
      setNote('')
      onDone()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <h3>매칭 요청 올리기</h3>
      <div className="grid2">
        <label className="field">날짜<input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
        <label className="field">코트<input value={court} onChange={(e) => setCourt(e.target.value)} placeholder="코트 이름" /></label>
        <label className="field">시작<input type="time" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="field">종료<input type="time" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <label className="field">
          형식
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="one_set">1세트</option>
            <option value="best_of_3">3세트</option>
            <option value="club_single_set_noad">1세트 노애드</option>
          </select>
        </label>
        <label className="field">
          스타일 선호
          <select value={style} onChange={(e) => setStyle(e.target.value)}>
            {STYLE_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>
      <label className="field" style={{ marginTop: 8 }}>
        메모
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="가볍게 한 세트 어때요" />
      </label>
      {err && <div className="banner bad" style={{ marginTop: 8 }}>{err}</div>}
      <button className="btn primary" style={{ marginTop: 10, width: '100%' }} disabled={busy} onClick={submit}>
        {busy ? '등록 중…' : '요청 등록'}
      </button>
    </div>
  )
}
