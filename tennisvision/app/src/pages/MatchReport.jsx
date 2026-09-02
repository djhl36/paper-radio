import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { CourtMap, BarList, Donut, RallyBuckets, Radar } from '../components/Charts.jsx'
import { END_REASON_KO, SHOT_KO, RESULT_KO, DIRECTION_KO, serveZoneKo } from '../lib/court.js'

const TABS = [
  ['summary', '요약'],
  ['coach', '코칭'],
  ['shots', '샷 분석'],
  ['calls', '판정'],
  ['highlights', '하이라이트'],
]
const AXIS_KO = {
  aggression: '공격성', power: '파워', consistency: '안정성', net_play: '네트',
  serve: '서브', return_game: '리턴', variety: '다양성', depth: '깊이',
  movement: '활동량', forehand_bias: '포핸드',
}

export default function MatchReport({ ctx, matchId }) {
  const [match, setMatch] = useState(null)
  const [shots, setShots] = useState([])
  const [side, setSide] = useState('near')
  const [tab, setTab] = useState('summary')
  const [error, setError] = useState(null)
  const videoRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([api.match(matchId), api.matchShots(matchId)])
      setMatch(m)
      setShots(s)
    } catch (e) { setError(e.message) }
  }, [matchId])
  useEffect(() => { load() }, [load])

  const seek = (t) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, t)
    v.play().catch(() => {})
    v.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (error) return <div className="page"><div className="banner bad">{error}</div></div>
  if (!match) return <div className="page"><div className="empty">불러오는 중…</div></div>

  // DB 에 등록된 선수 이름이 우선. 분석 당시 이름은 폴백.
  const names = {
    near: match.near?.name || match.playerNames?.near || '니어',
    far: match.far?.name || match.playerNames?.far || '파',
  }
  const stats = match.stats?.[side]
  const report = match.reports?.[side]
  const style = match.styles?.[side]
  const q = match.quality || {}

  return (
    <div className="page">
      <div className="card">
        <div className="row">
          <div>
            <div className="muted small">{match.playedAt?.slice(0, 10)} · {match.court || '코트 미기록'}</div>
            <div className="big" style={{ fontSize: 20 }}>{names.near} vs {names.far}</div>
            <div className="mono" style={{ marginTop: 4 }}>{match.score || '—'}</div>
          </div>
          <span className="spacer" />
          {q.overall != null && (
            <div className="center">
              <Donut value={q.overall} label="분석 신뢰도" size={78}
                color={q.overall >= 0.8 ? '#4ade80' : q.overall >= 0.5 ? '#fbbf24' : '#fb7185'} />
            </div>
          )}
        </div>
        {q.message && q.overall < 0.85 && (
          <div className="banner warn" style={{ marginTop: 10 }}>{q.message}</div>
        )}
        <div className="row wrap small muted" style={{ marginTop: 8, gap: 10 }}>
          <span>포인트 {match.points.length}</span>
          <span>판정 {match.calls.length}</span>
          <span>공 검출률 {Math.round((q.ballDetectionRatio || 0) * 100)}%</span>
          <span>캘리브레이션 {q.calibration}</span>
        </div>
      </div>

      {match.hasVideo && (
        <video ref={videoRef} className="stage" controls playsInline preload="metadata"
          src={api.videoUrl(matchId)} style={{ width: '100%', borderRadius: 12 }} />
      )}

      <div className="tabs">
        {TABS.map(([k, l]) => (
          <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      <div className="tabs">
        {['near', 'far'].map((s) => (
          <button key={s} className={side === s ? 'active' : ''} onClick={() => setSide(s)}>
            {names[s]}
          </button>
        ))}
      </div>

      {tab === 'summary' && <Summary match={match} stats={stats} names={names} side={side} onSeek={seek} />}
      {tab === 'coach' && <Coach report={report} style={style} />}
      {tab === 'shots' && <Shots shots={shots.filter((s) => s.side === side)} stats={stats} onSeek={seek} />}
      {tab === 'calls' && <Calls match={match} onSeek={seek} onReload={load} ctx={ctx} />}
      {tab === 'highlights' && <Highlights match={match} onSeek={seek} />}
    </div>
  )
}

// ---------- 요약 ----------
function Summary({ match, stats, names, side, onSeek }) {
  if (!stats) return <div className="empty">이 선수의 통계가 없습니다.</div>
  const c = stats.counts || {}
  const m = stats.metrics || {}
  const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)

  return (
    <>
      <div className="grid3">
        <Stat label="포인트 획득" value={`${stats.points_won}/${stats.points_played}`} />
        <Stat label="위너" value={c.winners ?? 0} />
        <Stat label="언포스드" value={c.unforcedErrors ?? 0} />
        <Stat label="에이스" value={c.aces ?? 0} />
        <Stat label="더블폴트" value={c.doubleFaults ?? 0} />
        <Stat label="네트 득점" value={`${c.netWon ?? 0}/${c.netPoints ?? 0}`} />
      </div>

      <div className="card">
        <h3>서브 / 리턴</h3>
        <div className="kv"><span className="k">퍼스트 서브 성공률</span><span className="v">{pct(m.first_serve_in_pct)}</span></div>
        <div className="kv"><span className="k">퍼스트 서브 득점률</span><span className="v">{pct(m.first_serve_won_pct)}</span></div>
        <div className="kv"><span className="k">세컨 서브 득점률</span><span className="v">{pct(m.second_serve_won_pct)}</span></div>
        <div className="kv"><span className="k">리턴 득점률</span><span className="v">{pct(m.return_won_pct)}</span></div>
        <div className="kv"><span className="k">브레이크포인트 방어</span><span className="v">{c.breakPointsSaved ?? 0}/{c.breakPointsFaced ?? 0}</span></div>
        <div className="kv"><span className="k">브레이크포인트 전환</span><span className="v">{c.breakPointsConverted ?? 0}/{c.breakPointsHad ?? 0}</span></div>
      </div>

      {stats.distributions?.serveZones && Object.keys(stats.distributions.serveZones).length > 0 && (
        <div className="card">
          <h3>서브 코스</h3>
          <BarList items={Object.entries(stats.distributions.serveZones).map(([k, v]) => ({
            label: serveZoneKo(k), value: v.count, display: `${v.count}회 (${Math.round(v.pct * 100)}%)`,
          }))} />
        </div>
      )}

      <div className="card">
        <h3>랠리 길이별 승률</h3>
        <RallyBuckets buckets={stats.distributions?.rallyBuckets} />
      </div>

      <div className="card">
        <h3>바운스 맵 ({names[side]}의 타구가 떨어진 지점)</h3>
        <div className="row" style={{ justifyContent: 'center' }}>
          <CourtMap bounces={(stats.distributions?.bounceMap || []).map((b) => ({ ...b }))} />
        </div>
        <div className="legend" style={{ marginTop: 8, justifyContent: 'center' }}>
          <span><i style={{ background: '#4ade80' }} />위너</span>
          <span><i style={{ background: '#fb7185' }} />에러</span>
          <span><i style={{ background: '#38bdf8' }} />진행</span>
        </div>
      </div>

      <div className="card">
        <h3>포인트 목록</h3>
        <div className="list">
          {match.points.map((p) => (
            <button key={p.idx} className="item" onClick={() => onSeek(p.tStart - 2)}>
              <div className="rank">{p.idx + 1}</div>
              <div style={{ flex: 1 }}>
                <div className="title">
                  {names[p.winnerSide]} 득점 · {END_REASON_KO[p.endReason] || p.endReason}
                </div>
                <div className="sub">
                  {p.rallyLength}구 · {p.serveNumber === 2 ? '세컨' : '퍼스트'} 서브 ·
                  {' '}{p.scoreAfter}
                </div>
              </div>
              {p.isMatchPoint && <span className="pill accent">MP</span>}
              {!p.isMatchPoint && p.isSetPoint && <span className="pill accent">SP</span>}
              {!p.isSetPoint && p.isBreakPoint && <span className="pill warn">BP</span>}
            </button>
          ))}
        </div>
      </div>
    </>
  )
}

function Stat({ label, value }) {
  return (
    <div className="card tight center">
      <div className="small muted">{label}</div>
      <div className="big" style={{ fontSize: 20 }}>{value}</div>
    </div>
  )
}

// ---------- 코칭 ----------
function Coach({ report, style }) {
  if (!report) return <div className="empty">코칭 리포트가 없습니다.</div>
  return (
    <>
      <div className="card">
        <h2>{report.headline}</h2>
        <p className="small">{report.summary}</p>
        <div className="small muted">데이터 신뢰도 {Math.round((report.data_confidence || 0) * 100)}%</div>
      </div>

      <div className="card">
        <h3>강점</h3>
        {report.strengths.length === 0 && <div className="empty">표본이 더 필요합니다.</div>}
        <div className="list">
          {report.strengths.map((s) => (
            <div key={s.key} className="row">
              <span className="pill good">+{s.z.toFixed(1)}</span>
              <span style={{ flex: 1 }}>{s.label}</span>
              <span className="mono">{s.display}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>보완점 &amp; 추천 드릴</h3>
        {report.weaknesses.length === 0 && <div className="empty">뚜렷한 약점이 없습니다.</div>}
        <div className="list">
          {report.weaknesses.map((s) => (
            <div key={s.key} className="card tight">
              <div className="row">
                <span className="pill bad">{s.z.toFixed(1)}</span>
                <span style={{ flex: 1 }}>{s.label}</span>
                <span className="mono">{s.display}</span>
              </div>
              {s.drill && <div className="small muted" style={{ marginTop: 6 }}>🎯 {s.drill}</div>}
              {s.note && <div className="small" style={{ color: '#fbbf24' }}>{s.note}</div>}
            </div>
          ))}
        </div>
      </div>

      {style?.vector && (
        <div className="card">
          <h3>이 경기의 플레이스타일</h3>
          <div className="row" style={{ justifyContent: 'center' }}>
            <Radar vector={style.vector} labels={AXIS_KO} size={250} />
          </div>
          <div className="center">
            <span className="pill accent">{style.archetype_ko}</span>
          </div>
          <p className="small muted center" style={{ marginTop: 8 }}>{style.description}</p>
        </div>
      )}
    </>
  )
}

// ---------- 샷 ----------
function Shots({ shots, stats, onSeek }) {
  const [type, setType] = useState('all')
  const types = useMemo(() => {
    const set = new Set(shots.map((s) => s.type))
    return ['all', ...set]
  }, [shots])
  const filtered = type === 'all' ? shots : shots.filter((s) => s.type === type)
  const speeds = filtered.map((s) => s.speedKmh).filter(Boolean)

  return (
    <>
      <div className="tabs">
        {types.map((t) => (
          <button key={t} className={type === t ? 'active' : ''} onClick={() => setType(t)}>
            {t === 'all' ? '전체' : (SHOT_KO[t] || t)}
          </button>
        ))}
      </div>

      <div className="grid3">
        <Stat label="샷 수" value={filtered.length} />
        <Stat label="평균 구속" value={speeds.length ? `${Math.round(speeds.reduce((a, b) => a + b, 0) / speeds.length)}` : '—'} />
        <Stat label="최고 구속" value={speeds.length ? `${Math.round(Math.max(...speeds))}` : '—'} />
      </div>
      <div className="small muted center">구속은 지면 투영 기준의 평균 속도(km/h)로, 실제 라켓 스피드보다 낮게 나옵니다.</div>

      <div className="card">
        <h3>코스 분포</h3>
        <div className="row" style={{ justifyContent: 'center' }}>
          <CourtMap
            bounces={filtered.filter((s) => s.bounce).map((s) => ({
              x: s.bounce[0], y: s.bounce[1], result: s.result,
            }))}
            shots={filtered.filter((s) => s.contact && s.bounce)}
          />
        </div>
      </div>

      {stats?.distributions?.direction && (
        <div className="card">
          <h3>방향</h3>
          <BarList items={Object.entries(stats.distributions.direction).map(([k, v]) => ({
            label: DIRECTION_KO[k] || k, value: v.count,
            display: `${v.count} (${Math.round(v.pct * 100)}%)`,
          }))} />
        </div>
      )}

      <div className="card">
        <h3>샷 목록</h3>
        <div className="list">
          {filtered.slice(0, 120).map((s) => (
            <button key={s.idx} className="item" onClick={() => onSeek(s.t - 1.5)}>
              <div style={{ flex: 1 }}>
                <div className="title">
                  {SHOT_KO[s.type] || s.type}
                  {s.serveZone ? ` · ${serveZoneKo(s.serveZone)}` : ''}
                </div>
                <div className="sub">
                  {s.speedKmh ? `${s.speedKmh}km/h · ` : ''}
                  {s.depthM != null ? `깊이 ${s.depthM}m · ` : ''}
                  {DIRECTION_KO[s.direction] || ''}
                </div>
              </div>
              <span className={`pill ${s.result === 'winner' || s.result === 'ace' ? 'good' : s.result.endsWith('error') || s.result === 'double_fault' ? 'bad' : ''}`}>
                {RESULT_KO[s.result] || s.result}
              </span>
            </button>
          ))}
        </div>
      </div>
    </>
  )
}

// ---------- 판정 ----------
function Calls({ match, onSeek, onReload, ctx }) {
  const [busy, setBusy] = useState(null)
  const flip = async (call, kind) => {
    setBusy(call.id)
    try {
      await api.overrideCall(match.id, call.id, kind, ctx.me?.id)
      await onReload()
    } finally { setBusy(null) }
  }
  const close = match.calls.filter((c) => c.tooClose).length

  return (
    <>
      <div className="card">
        <h3>판정 {match.calls.length}건</h3>
        <p className="small muted">
          라인에서 오차 예산 안에 들어온 {close}건은 <b>판독 불가</b>로 표시됩니다.
          자동 판정이 틀렸다면 직접 뒤집을 수 있고, 그 기록도 함께 남습니다.
        </p>
      </div>
      <div className="list">
        {match.calls.map((c) => (
          <div key={c.id} className="card tight">
            <div className="row">
              <span className={`pill ${c.tooClose ? 'warn' : c.kind === 'in' ? 'good' : 'bad'}`}>
                {c.tooClose ? '판독 불가' : c.kind === 'in' ? '인' : c.kind === 'fault' ? '폴트' : '아웃'}
              </span>
              <div style={{ flex: 1 }}>
                <div className="small">
                  {c.marginCm >= 0 ? '라인 안쪽' : '라인 바깥'} {Math.abs(c.marginCm).toFixed(0)}cm
                  <span className="muted"> (오차 ±{c.errorBudgetCm.toFixed(0)}cm)</span>
                </div>
                <div className="sub small muted">
                  {c.t.toFixed(1)}초 · 포인트 {c.pointIdx + 1}
                  {c.overridden && ' · 사용자 수정됨'}
                </div>
              </div>
              <button className="btn sm ghost" onClick={() => onSeek(c.t - 1.5)}>재생</button>
            </div>
            <div className="row" style={{ marginTop: 7, gap: 6 }}>
              <button className="btn sm" disabled={busy === c.id} onClick={() => flip(c, 'in')}>인으로</button>
              <button className="btn sm" disabled={busy === c.id} onClick={() => flip(c, 'out')}>아웃으로</button>
              <span className="spacer" />
              <div style={{ width: 84 }}>
                <CourtMap height={150} bounces={[{ x: c.court[0], y: c.court[1], kind: c.kind, tooClose: c.tooClose }]} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

// ---------- 하이라이트 ----------
function Highlights({ match, onSeek }) {
  if (!match.highlights.length) return <div className="empty">선정된 하이라이트가 없습니다.</div>
  return (
    <div className="list">
      {match.highlights.map((h) => (
        <div key={h.id} className="card tight">
          <div className="row">
            <div style={{ flex: 1 }}>
              <div className="title">{h.title}</div>
              <div className="sub">{h.caption}</div>
              <div className="row wrap" style={{ gap: 5, marginTop: 5 }}>
                {h.tags.map((t) => <span key={t} className="pill">{t}</span>)}
              </div>
            </div>
            <span className="pill accent">{Math.round(h.score * 100)}</span>
          </div>
          <div className="row" style={{ marginTop: 8, gap: 6 }}>
            <button className="btn sm" onClick={() => onSeek(h.start)}>
              ▶ {h.start.toFixed(1)}s ~ {h.end.toFixed(1)}s
            </button>
            {h.hasClip && (
              <a className="btn sm" href={api.clipUrl(h.id)} target="_blank" rel="noreferrer">클립 열기</a>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
