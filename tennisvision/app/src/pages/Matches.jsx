import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { navigate } from '../App.jsx'

const FORMATS = [
  ['best_of_3', '3세트'],
  ['one_set', '1세트'],
  ['club_single_set_noad', '1세트 노애드'],
  ['pro_set', '프로셋(8게임)'],
  ['fast4', 'Fast4'],
]
const W = 960
const H = 540

export default function Matches({ ctx }) {
  const { me, players } = ctx
  const [matches, setMatches] = useState([])
  const [showUpload, setShowUpload] = useState(false)
  const [jobs, setJobs] = useState({})

  const load = useCallback(async () => {
    try { setMatches(await api.matches()) } catch { /* 무시 */ }
  }, [])
  useEffect(() => { load() }, [load])

  // 분석 중인 경기 폴링
  useEffect(() => {
    const pending = matches.filter((m) => ['pending', 'analyzing'].includes(m.status))
    if (!pending.length) return
    const t = setInterval(async () => {
      const next = {}
      for (const m of pending) {
        try { next[m.id] = await api.matchStatus(m.id) } catch { /* 무시 */ }
      }
      setJobs(next)
      if (Object.values(next).some((j) => j.stage === 'done' || j.stage === 'failed')) load()
    }, 2500)
    return () => clearInterval(t)
  }, [matches, load])

  return (
    <div className="page">
      <div className="row">
        <h2 style={{ margin: 0 }}>경기</h2>
        <span className="spacer" />
        <button className="btn primary sm" onClick={() => setShowUpload(true)}>+ 영상 분석</button>
      </div>

      {matches.length === 0 && <div className="empty">아직 경기가 없습니다. 영상을 올려보세요.</div>}

      <div className="list">
        {matches.map((m) => {
          const job = jobs[m.id]
          return (
            <button key={m.id} className="item"
              onClick={() => m.status === 'done' && navigate(`report/${m.id}`)}>
              <div style={{ flex: 1 }}>
                <div className="title">{m.near.name} vs {m.far.name}</div>
                <div className="sub">
                  {m.score || '—'} · {m.playedAt?.slice(0, 10)} · {m.source === 'live' ? '라이브' : '업로드'}
                  {m.court ? ` · ${m.court}` : ''}
                </div>
                {job && ['pending', 'analyzing'].includes(m.status) && (
                  <div className="bar" style={{ marginTop: 6 }}>
                    <i style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
                  </div>
                )}
              </div>
              <StatusPill status={m.status} job={job} quality={m.quality} />
            </button>
          )
        })}
      </div>

      {showUpload && (
        <UploadSheet ctx={ctx} onClose={() => { setShowUpload(false); load() }} />
      )}
    </div>
  )
}

function StatusPill({ status, job, quality }) {
  if (status === 'analyzing' || status === 'pending') {
    return <span className="pill warn">{job?.stage || '대기'} {Math.round((job?.progress || 0) * 100)}%</span>
  }
  if (status === 'failed') return <span className="pill bad">실패</span>
  const q = quality?.overall
  if (q != null) {
    const cls = q >= 0.8 ? 'good' : q >= 0.5 ? 'warn' : 'bad'
    return <span className={`pill ${cls}`}>신뢰도 {Math.round(q * 100)}</span>
  }
  return <span className="pill">완료</span>
}

// ---------- 업로드 + 캘리브레이션 ----------
function UploadSheet({ ctx, onClose }) {
  const { me, players } = ctx
  const [file, setFile] = useState(null)
  const [nearId, setNearId] = useState(me?.id ?? null)
  const [farId, setFarId] = useState(
    () => players.find((p) => p.id !== me?.id)?.id ?? null,
  )
  const [format, setFormat] = useState('best_of_3')
  const [firstServer, setFirstServer] = useState('near')
  const [corners, setCorners] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [frameReady, setFrameReady] = useState(false)
  const videoRef = useRef(null)
  const canvasRef = useRef(null)

  const onPick = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setCorners([])
    setFrameReady(false)
    const v = videoRef.current
    v.src = URL.createObjectURL(f)
    v.onloadeddata = () => {
      v.currentTime = Math.min(2, (v.duration || 4) / 2)
    }
    v.onseeked = () => {
      const ctx2 = canvasRef.current.getContext('2d')
      ctx2.drawImage(v, 0, 0, W, H)
      setFrameReady(true)
    }
  }

  const draw = useCallback(() => {
    if (!frameReady) return
    const c = canvasRef.current
    const ctx2 = c.getContext('2d')
    ctx2.drawImage(videoRef.current, 0, 0, W, H)
    ctx2.fillStyle = '#d6f24a'
    ctx2.strokeStyle = '#d6f24a'
    ctx2.lineWidth = 2
    corners.forEach(([x, y], i) => {
      ctx2.beginPath(); ctx2.arc(x, y, 9, 0, Math.PI * 2); ctx2.fill()
      ctx2.fillStyle = '#0b1220'; ctx2.font = 'bold 13px sans-serif'
      ctx2.textAlign = 'center'; ctx2.textBaseline = 'middle'
      ctx2.fillText(String(i + 1), x, y + 1)
      ctx2.fillStyle = '#d6f24a'
    })
    if (corners.length > 1) {
      ctx2.beginPath()
      ctx2.moveTo(corners[0][0], corners[0][1])
      corners.slice(1).forEach(([x, y]) => ctx2.lineTo(x, y))
      if (corners.length === 4) ctx2.closePath()
      ctx2.stroke()
    }
  }, [corners, frameReady])
  useEffect(() => { draw() }, [draw])

  const onTap = (e) => {
    if (corners.length >= 4) return
    const rect = e.currentTarget.getBoundingClientRect()
    setCorners([...corners, [
      Math.round(((e.clientX - rect.left) / rect.width) * W),
      Math.round(((e.clientY - rect.top) / rect.height) * H),
    ]])
  }

  const submit = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('video', file)
      if (nearId) fd.append('nearPlayerId', String(nearId))
      if (farId) fd.append('farPlayerId', String(farId))
      fd.append('format', format)
      fd.append('firstServerSide', firstServer)
      if (corners.length === 4) {
        // 캘리브레이션 점은 원본 영상 해상도 기준이어야 한다
        const v = videoRef.current
        const sx = (v.videoWidth || W) / W
        const sy = (v.videoHeight || H) / H
        fd.append('calibration', JSON.stringify({
          imagePoints: corners.map(([x, y]) => [x * sx, y * sy]),
        }))
      }
      await api.uploadMatch(fd)
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sheet" onClick={(e) => e.target.classList.contains('sheet') && onClose()}>
      <div className="inner">
        <div className="row">
          <h2 style={{ margin: 0 }}>경기 영상 분석</h2>
          <span className="spacer" />
          <button className="btn sm ghost" onClick={onClose}>닫기</button>
        </div>

        <p className="small muted">
          삼각대 고정 촬영이 필요합니다. 코트 4모서리를 지정하면 정확도가 크게 올라갑니다
          (지정하지 않으면 자동 인식을 시도합니다).
        </p>

        <input type="file" accept="video/*" onChange={onPick} style={{ marginTop: 8 }} />

        <video ref={videoRef} style={{ display: 'none' }} muted playsInline />
        <div className="stage" style={{ marginTop: 10, display: file ? 'block' : 'none' }}>
          <canvas ref={canvasRef} width={W} height={H} onClick={onTap} />
        </div>
        {file && (
          <div className="row wrap" style={{ marginTop: 8 }}>
            <span className="pill">{corners.length}/4 모서리</span>
            <button className="btn sm" onClick={() => setCorners(corners.slice(0, -1))}
              disabled={!corners.length}>마지막 취소</button>
            <button className="btn sm" onClick={() => setCorners([])}>지우기</button>
          </div>
        )}

        <div className="grid2" style={{ marginTop: 12 }}>
          <label className="field">
            니어 사이드 선수
            <select value={nearId ?? ''} onChange={(e) => setNearId(Number(e.target.value))}>
              {players.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="field">
            파 사이드 선수
            <select value={farId ?? ''} onChange={(e) => setFarId(Number(e.target.value))}>
              {players.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="field">
            경기 형식
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              {FORMATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field">
            첫 서브
            <select value={firstServer} onChange={(e) => setFirstServer(e.target.value)}>
              <option value="near">니어 사이드</option>
              <option value="far">파 사이드</option>
            </select>
          </label>
        </div>

        {error && <div className="banner bad" style={{ marginTop: 10 }}>{error}</div>}

        <button className="btn primary" style={{ marginTop: 14, width: '100%' }}
          disabled={!file || busy} onClick={submit}>
          {busy ? '업로드 중…' : '분석 시작'}
        </button>
      </div>
    </div>
  )
}
