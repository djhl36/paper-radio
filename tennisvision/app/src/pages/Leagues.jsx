import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { navigate } from '../App.jsx'

const KIND_KO = { round_robin: '풀리그', single_elim: '토너먼트', ladder: '사다리' }
const STATUS_KO = { open: '모집 중', running: '진행 중', finished: '종료' }

export default function Leagues({ ctx, leagueId }) {
  if (leagueId) return <LeagueDetail ctx={ctx} leagueId={leagueId} />
  return <LeagueList ctx={ctx} />
}

function LeagueList({ ctx }) {
  const [leagues, setLeagues] = useState([])
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => setLeagues(await api.leagues()), [])
  useEffect(() => { load() }, [load])

  return (
    <div className="page">
      <div className="row">
        <h2 style={{ margin: 0 }}>리그 &amp; 대회</h2>
        <span className="spacer" />
        <button className="btn primary sm" onClick={() => setCreating(true)}>+ 만들기</button>
      </div>

      <div className="list">
        {leagues.map((l) => (
          <button key={l.id} className="item" onClick={() => navigate(`leagues/${l.id}`)}>
            <div style={{ flex: 1 }}>
              <div className="title">{l.name}</div>
              <div className="sub">
                {KIND_KO[l.kind] || l.kind} · {l.players}/{l.maxPlayers}명 · {l.court || '코트 미정'}
                {l.ratingMin ? ` · 레이팅 ${Math.round(l.ratingMin)}+` : ''}
              </div>
            </div>
            <span className={`pill ${l.status === 'running' ? 'good' : l.status === 'open' ? 'accent' : ''}`}>
              {STATUS_KO[l.status] || l.status}
            </span>
          </button>
        ))}
        {leagues.length === 0 && <div className="empty">아직 리그가 없습니다.</div>}
      </div>

      {creating && <CreateSheet onClose={() => { setCreating(false); load() }} />}
    </div>
  )
}

function CreateSheet({ onClose }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState('round_robin')
  const [court, setCourt] = useState('')
  const [maxPlayers, setMaxPlayers] = useState(8)
  const [ratingMin, setRatingMin] = useState('')
  const [desc, setDesc] = useState('')
  const [err, setErr] = useState(null)

  const submit = async () => {
    try {
      await api.createLeague({
        name, kind, court, maxPlayers: Number(maxPlayers),
        ratingMin: ratingMin ? Number(ratingMin) : null, description: desc,
      })
      onClose()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="sheet" onClick={(e) => e.target.classList.contains('sheet') && onClose()}>
      <div className="inner">
        <h2>리그 만들기</h2>
        <div className="grid2">
          <label className="field">이름<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field">
            형식
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="round_robin">풀리그</option>
              <option value="single_elim">단판 토너먼트</option>
              <option value="ladder">사다리</option>
            </select>
          </label>
          <label className="field">코트<input value={court} onChange={(e) => setCourt(e.target.value)} /></label>
          <label className="field">정원<input type="number" value={maxPlayers} onChange={(e) => setMaxPlayers(e.target.value)} /></label>
          <label className="field">최소 레이팅<input type="number" value={ratingMin} onChange={(e) => setRatingMin(e.target.value)} placeholder="제한 없음" /></label>
        </div>
        <label className="field" style={{ marginTop: 8 }}>
          설명<input value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        {err && <div className="banner bad" style={{ marginTop: 8 }}>{err}</div>}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn ghost" onClick={onClose}>취소</button>
          <span className="spacer" />
          <button className="btn primary" onClick={submit} disabled={!name}>만들기</button>
        </div>
      </div>
    </div>
  )
}

function LeagueDetail({ ctx, leagueId }) {
  const { me } = ctx
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('standings')
  const [err, setErr] = useState(null)
  const [resultFor, setResultFor] = useState(null)

  const load = useCallback(async () => {
    try { setData(await api.league(leagueId)) } catch (e) { setErr(e.message) }
  }, [leagueId])
  useEffect(() => { load() }, [load])

  if (err) return <div className="page"><div className="banner bad">{err}</div></div>
  if (!data) return <div className="page"><div className="empty">불러오는 중…</div></div>

  const joined = data.standings.some((s) => s.playerId === me?.id)

  const act = async (fn) => {
    setErr(null)
    try { await fn(); await load() } catch (e) { setErr(e.message) }
  }

  return (
    <div className="page">
      <button className="btn sm ghost" style={{ alignSelf: 'flex-start' }} onClick={() => navigate('leagues')}>
        ← 리그 목록
      </button>

      <div className="card">
        <div className="row">
          <div>
            <div className="big" style={{ fontSize: 19 }}>{data.name}</div>
            <div className="small muted">
              {KIND_KO[data.kind]} · {data.players}/{data.maxPlayers}명 · {data.court || '코트 미정'}
            </div>
          </div>
          <span className="spacer" />
          <span className="pill accent">{STATUS_KO[data.status]}</span>
        </div>
        {data.description && <p className="small muted">{data.description}</p>}
        <div className="row" style={{ marginTop: 8, gap: 6 }}>
          {!joined && data.status === 'open' && me && (
            <button className="btn primary sm" onClick={() => act(() => api.joinLeague(leagueId, me.id))}>
              참가하기
            </button>
          )}
          {data.status === 'open' && (
            <button className="btn sm" onClick={() => act(() => api.startLeague(leagueId))}>
              리그 시작 (대진 생성)
            </button>
          )}
        </div>
      </div>

      <div className="tabs">
        {[['standings', '순위표'], ['bracket', '대진']].map(([k, l]) => (
          <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === 'standings' && (
        <div className="list">
          {data.standings.map((s) => (
            <button key={s.playerId} className="item" onClick={() => navigate(`profile/${s.playerId}`)}>
              <div className="rank">{s.rank}</div>
              <div style={{ flex: 1 }}>
                <div className="title">{s.name} {s.playerId === me?.id && <span className="pill accent">나</span>}</div>
                <div className="sub">
                  {s.wins}승 {s.losses}패 · 게임 {s.gamesWon}-{s.gamesLost} ({s.gameDiff >= 0 ? '+' : ''}{s.gameDiff})
                </div>
              </div>
              <div className="center">
                <div className="mono">{s.points}점</div>
                <div className="small muted">{s.rating}</div>
              </div>
            </button>
          ))}
          {data.standings.length === 0 && <div className="empty">참가자가 없습니다.</div>}
        </div>
      )}

      {tab === 'bracket' && (
        <div className="list">
          {data.bracket.rounds.map((r) => (
            <div key={r.round} className="card">
              <h3>{data.kind === 'single_elim' ? roundName(r.round, data.bracket.rounds.length) : `${r.round}라운드`}</h3>
              <div className="list">
                {r.fixtures.map((f) => (
                  <div key={f.id} className="item" style={{ cursor: 'default' }}>
                    <div style={{ flex: 1 }}>
                      <div className="title">
                        <span style={{ color: f.winnerId === f.player1?.id ? '#4ade80' : undefined }}>
                          {f.player1?.name || '—'}
                        </span>
                        {' vs '}
                        <span style={{ color: f.winnerId === f.player2?.id ? '#4ade80' : undefined }}>
                          {f.player2?.name || '—'}
                        </span>
                      </div>
                      <div className="sub">
                        {f.scheduledAt?.slice(0, 10)} {f.court || ''} {f.score && `· ${f.score}`}
                      </div>
                    </div>
                    {f.status === 'played'
                      ? <span className="pill good">완료</span>
                      : f.player1?.id && f.player2?.id
                        ? <button className="btn sm" onClick={() => setResultFor(f)}>결과 입력</button>
                        : <span className="pill">대기</span>}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {data.bracket.rounds.length === 0 && (
            <div className="empty">
              {data.kind === 'ladder' ? '사다리 리그는 도전 방식으로 진행됩니다.' : '아직 대진이 없습니다.'}
            </div>
          )}
        </div>
      )}

      {resultFor && (
        <ResultSheet fixture={resultFor} onClose={() => { setResultFor(null); load() }} />
      )}
    </div>
  )
}

function roundName(round, total) {
  const fromEnd = total - round
  return ['결승', '준결승', '8강', '16강', '32강'][fromEnd] || `${round}라운드`
}

function ResultSheet({ fixture, onClose }) {
  const [winnerId, setWinnerId] = useState(fixture.player1?.id)
  const [wg, setWg] = useState(6)
  const [lg, setLg] = useState(3)
  const [err, setErr] = useState(null)

  const submit = async () => {
    try {
      await api.fixtureResult(fixture.id, {
        winnerId: Number(winnerId), winnerGames: Number(wg), loserGames: Number(lg),
      })
      onClose()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="sheet" onClick={(e) => e.target.classList.contains('sheet') && onClose()}>
      <div className="inner">
        <h2>결과 입력</h2>
        <label className="field">
          승자
          <select value={winnerId} onChange={(e) => setWinnerId(e.target.value)}>
            <option value={fixture.player1?.id}>{fixture.player1?.name}</option>
            <option value={fixture.player2?.id}>{fixture.player2?.name}</option>
          </select>
        </label>
        <div className="grid2" style={{ marginTop: 8 }}>
          <label className="field">승자 게임<input type="number" value={wg} onChange={(e) => setWg(e.target.value)} /></label>
          <label className="field">패자 게임<input type="number" value={lg} onChange={(e) => setLg(e.target.value)} /></label>
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>
          결과를 넣으면 순위표와 Glicko-2 레이팅이 함께 갱신됩니다.
        </p>
        {err && <div className="banner bad">{err}</div>}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn ghost" onClick={onClose}>취소</button>
          <span className="spacer" />
          <button className="btn primary" onClick={submit}>저장</button>
        </div>
      </div>
    </div>
  )
}
