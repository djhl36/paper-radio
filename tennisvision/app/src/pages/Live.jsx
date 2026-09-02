import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, liveSocketUrl } from '../lib/api.js'
import { navigate } from '../App.jsx'

const W = 960
const H = 540
const HIDDEN = {
  position: 'absolute', width: 1, height: 1, opacity: 0.01,
  pointerEvents: 'none', left: 0, top: 0,
}
const CORNER_LABELS = ['① 니어 왼쪽 모서리', '② 니어 오른쪽 모서리', '③ 파 오른쪽 모서리', '④ 파 왼쪽 모서리']
const FORMATS = [
  ['one_set', '1세트'],
  ['best_of_3', '3세트'],
  ['club_single_set_noad', '1세트 노애드'],
  ['fast4', 'Fast4'],
  ['pro_set', '프로셋(8게임)'],
]

export default function Live({ ctx }) {
  const { me, players } = ctx
  const videoRef = useRef(null)
  const captureRef = useRef(null)
  const displayRef = useRef(null)
  const wsRef = useRef(null)
  const stateRef = useRef({ trail: [], overlay: [], lastCall: null, corners: [], streaming: false })
  const rafRef = useRef(0)
  const lastSendRef = useRef(0)
  const sentRef = useRef(0)
  const handlerRef = useRef(null)

  const [phase, setPhase] = useState('idle')       // idle | calibrate | live | done
  const [corners, setCorners] = useState([])
  const [score, setScore] = useState(null)
  const [call, setCall] = useState(null)
  const [log, setLog] = useState([])
  const [warning, setWarning] = useState(null)
  const [stats, setStats] = useState({ fps: 0, sent: 0 })
  const [voice, setVoice] = useState(true)
  const [fpsTarget, setFpsTarget] = useState(15)
  const [format, setFormat] = useState('one_set')
  const [nearId, setNearId] = useState(null)
  const [farId, setFarId] = useState(null)
  const [firstServer, setFirstServer] = useState('near')
  const [error, setError] = useState(null)

  useEffect(() => {
    // me 가 아직 안 왔을 때 상대를 정하면 자기 자신이 뽑힐 수 있다. me 를 기다린다.
    if (!me?.id) return
    if (nearId == null) setNearId(me.id)
    if (farId == null && players.length > 1) {
      setFarId(players.find((p) => p.id !== me.id)?.id ?? null)
    }
  }, [me?.id, players, nearId, farId])

  const say = useCallback((text) => {
    if (!voice || !text || !('speechSynthesis' in window)) return
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ko-KR'
    u.rate = 1.1
    speechSynthesis.cancel()
    speechSynthesis.speak(u)
  }, [voice])

  const pushLog = useCallback((line) => {
    setLog((prev) => [`${new Date().toLocaleTimeString('ko-KR', { hour12: false })}  ${line}`, ...prev].slice(0, 60))
  }, [])

  // ---------- 카메라 ----------
  const startCamera = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      const v = videoRef.current
      v.srcObject = stream
      await v.play()
      setPhase('calibrate')
    } catch (e) {
      setError('카메라를 열 수 없습니다: ' + e.message + ' (HTTPS 또는 localhost 에서만 동작합니다)')
    }
  }, [])

  const useSampleVideo = useCallback(async () => {
    // 카메라가 없는 데스크톱에서 데모용으로 서버에 있는 영상 경기를 재생한다.
    setError(null)
    try {
      const list = await api.matches()
      const withVideo = list.find((m) => m.hasVideo)
      if (!withVideo) {
        setError('서버에 영상이 있는 경기가 없습니다. tools/simulate.py 로 샘플을 만들고 seed 를 실행하세요.')
        return
      }
      const v = videoRef.current
      v.srcObject = null
      v.src = api.videoUrl(withVideo.id)
      v.loop = false
      v.muted = true
      setPhase('calibrate')
      try {
        await v.play()
      } catch {
        // 자동 재생이 막히면 첫 프레임만 그려 두고 캘리브레이션은 진행할 수 있게 한다
        v.currentTime = 2
        setError('브라우저가 자동 재생을 막았습니다. 코트 4모서리를 지정한 뒤 "판정 시작"을 누르면 재생됩니다.')
      }
    } catch (e) {
      setError('샘플 영상을 재생할 수 없습니다: ' + e.message)
    }
  }, [])

  // ---------- 렌더 루프 ----------
  useEffect(() => {
    if (phase === 'idle') return
    let frames = 0
    let t0 = performance.now()

    const loop = () => {
      rafRef.current = requestAnimationFrame(loop)
      const v = videoRef.current
      const cap = captureRef.current
      const disp = displayRef.current
      if (!v || !cap || !disp || v.readyState < 2) return

      const cctx = cap.getContext('2d')
      cctx.drawImage(v, 0, 0, W, H)

      const dctx = disp.getContext('2d')
      dctx.drawImage(cap, 0, 0)
      drawOverlay(dctx, stateRef.current, phase)

      frames += 1
      const now = performance.now()
      if (now - t0 > 1000) {
        setStats({ fps: Math.round((frames * 1000) / (now - t0)), sent: sentRef.current })
        frames = 0
        t0 = now
      }

      if (stateRef.current.streaming && wsRef.current?.readyState === 1) {
        const interval = 1000 / fpsTarget
        if (now - lastSendRef.current >= interval) {
          lastSendRef.current = now
          cap.toBlob(
            (blob) => {
              if (blob && wsRef.current?.readyState === 1 && wsRef.current.bufferedAmount < 1_500_000) {
                blob.arrayBuffer().then((buf) => {
                  wsRef.current?.send(buf)
                  sentRef.current += 1
                })
              }
            },
            'image/jpeg',
            0.62,
          )
        }
      }
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [phase, fpsTarget])

  // ---------- 캘리브레이션 탭 ----------
  const onTap = useCallback((e) => {
    if (phase !== 'calibrate' || corners.length >= 4) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * W
    const y = ((e.clientY - rect.top) / rect.height) * H
    const next = [...corners, [Math.round(x), Math.round(y)]]
    setCorners(next)
    stateRef.current.corners = next
  }, [phase, corners])

  const undoCorner = () => {
    const next = corners.slice(0, -1)
    setCorners(next)
    stateRef.current.corners = next
  }

  const autoDetect = async () => {
    setError(null)
    captureRef.current.toBlob(async (blob) => {
      try {
        const r = await api.calibrateAuto(blob)
        const pts = r.corners.map((p) => [Math.round(p[0]), Math.round(p[1])])
        setCorners(pts)
        stateRef.current.corners = pts
        stateRef.current.overlay = r.overlay
        pushLog(`코트 자동 인식 (품질 ${r.quality})`)
      } catch (e) {
        setError('자동 인식 실패: ' + e.message + ' — 4모서리를 직접 탭해 주세요.')
      }
    }, 'image/jpeg', 0.9)
  }

  // ---------- 세션 시작 ----------
  const startLive = useCallback(() => {
    if (corners.length !== 4) return
    videoRef.current?.play().catch(() => {})
    const sessionId = 'live-' + Math.random().toString(36).slice(2, 10)
    const ws = new WebSocket(liveSocketUrl(sessionId))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      const nearName = players.find((p) => p.id === nearId)?.name || '니어'
      const farName = players.find((p) => p.id === farId)?.name || '파'
      ws.send(JSON.stringify({
        type: 'init',
        calibration: { imagePoints: corners, frameSize: [W, H] },
        format,
        names: { near: nearName, far: farName },
        firstServerSide: firstServer,
        fps: fpsTarget,
      }))
    }
    // 최신 핸들러를 ref 로 참조한다 (세션 도중 음성 토글 등으로 핸들러가 바뀌어도 반영)
    ws.onmessage = (ev) => handlerRef.current?.(JSON.parse(ev.data))
    ws.onerror = () => setError('WebSocket 오류 — 서버가 떠 있는지 확인하세요.')
    ws.onclose = () => { stateRef.current.streaming = false }
  }, [corners, format, firstServer, fpsTarget, nearId, farId, players])

  const handleMessage = useCallback((m) => {
    switch (m.type) {
      case 'ready':
        stateRef.current.overlay = m.overlay || []
        stateRef.current.streaming = true
        setPhase('live')
        setScore(m.status?.score)
        pushLog('세션 시작 — 캘리브레이션 ' + m.status?.calibrationQuality)
        say('경기를 시작합니다')
        break
      case 'ball': {
        const t = stateRef.current.trail
        t.push(m.image)
        if (t.length > 24) t.shift()
        break
      }
      case 'call':
        stateRef.current.lastCall = m
        setCall(m)
        pushLog(`판정 ${m.announce}`)
        if (m.tooClose) say('판독 불가')
        else if (m.kind === 'out') say('아웃')
        else if (m.kind === 'fault') say('폴트')
        break
      case 'point':
        setScore(m.score)
        pushLog(`포인트 → ${m.winnerSide === 'near' ? '니어' : '파'} (${m.reason}, ${m.rallyLength}구) ${m.score.scoreString}`)
        say(m.announce)
        break
      case 'fault':
        setScore(m.score)
        pushLog('폴트 — 세컨 서브')
        break
      case 'let':
        pushLog('레트 — 다시')
        say('레트')
        break
      case 'score':
        setScore(m.score)
        if (m.announce) say(m.announce)
        break
      case 'warning':
        setWarning(m.message)
        break
      case 'match_end':
        setScore(m.score)
        say('게임 세트 앤 매치')
        pushLog('경기 종료')
        break
      case 'finished':
        stateRef.current.streaming = false
        setPhase('done')
        pushLog(`저장 완료 — 포인트 ${m.points}개, 하이라이트 ${m.highlights}개`)
        if (m.matchId) setTimeout(() => navigate(`report/${m.matchId}`), 800)
        break
      case 'error':
        setError(m.message)
        break
      default:
        break
    }
  }, [pushLog, say])

  useEffect(() => { handlerRef.current = handleMessage }, [handleMessage])

  const send = (obj) => wsRef.current?.readyState === 1 && wsRef.current.send(JSON.stringify(obj))

  const finish = () => {
    stateRef.current.streaming = false
    send({ type: 'finish', nearPlayerId: nearId, farPlayerId: farId, format })
  }

  // 화면이 꺼지거나 앱이 백그라운드로 가면 requestAnimationFrame 이 멈춰서
  // 프레임 전송이 끊긴다. 조용히 죽는 대신 사용자에게 알린다.
  useEffect(() => {
    const onVis = () => {
      if (document.hidden && stateRef.current.streaming) {
        setWarning('화면이 꺼지거나 다른 앱으로 전환되면 프레임 전송이 멈춥니다. 화면을 켜 두세요.')
      } else if (!document.hidden) {
        setWarning((w) => (w && w.startsWith('화면이 꺼지거나') ? null : w))
      }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  useEffect(() => () => {
    wsRef.current?.close()
    const v = videoRef.current
    if (v?.srcObject) v.srcObject.getTracks().forEach((t) => t.stop())
  }, [])

  return (
    <div className="page">
      {/* 캡처용 소스. display:none 으로 숨기면 크롬이 "보이지 않는 비디오"로 보고
          절전 정책으로 재생을 멈춘다. 그래서 화면 밖에 1px 로 살려 둔다. */}
      <video ref={videoRef} playsInline muted style={HIDDEN} />
      <canvas ref={captureRef} width={W} height={H} style={HIDDEN} />

      {error && <div className="banner bad">{error}</div>}
      {warning && <div className="banner warn">{warning}</div>}

      {phase === 'idle' && (
        <div className="card">
          <h2>라이브 심판</h2>
          <p className="muted small">
            삼각대에 폰을 고정하고 베이스라인 뒤 높은 곳에서 코트 전체가 보이게 놓으세요.
            코트 4모서리를 탭하면 인/아웃 판정과 점수 계산이 시작됩니다.
          </p>
          <div className="grid2" style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={startCamera}>카메라 사용</button>
            <button className="btn" onClick={useSampleVideo}>샘플 영상으로 체험</button>
          </div>
        </div>
      )}

      {phase !== 'idle' && (
        <>
          <div className="stage">
            <canvas ref={displayRef} width={W} height={H} onClick={onTap} />
          </div>

          {phase === 'calibrate' && (
            <div className="card">
              <h3>코트 4모서리 지정 ({corners.length}/4)</h3>
              <p className="small">
                {corners.length < 4
                  ? `화면에서 ${CORNER_LABELS[corners.length]}를 탭하세요 (복식 코트 기준)`
                  : '4점이 모두 지정되었습니다. 설정을 확인하고 시작하세요.'}
              </p>
              <div className="row wrap" style={{ marginTop: 8 }}>
                <button className="btn sm" onClick={undoCorner} disabled={!corners.length}>마지막 취소</button>
                <button className="btn sm" onClick={() => { setCorners([]); stateRef.current.corners = [] }}>전체 지우기</button>
                <button className="btn sm" onClick={autoDetect}>자동 인식 시도</button>
              </div>

              <div className="grid2" style={{ marginTop: 12 }}>
                <label className="field">
                  니어 사이드(카메라 쪽) 선수
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
                <label className="field">
                  전송 프레임레이트 ({fpsTarget}fps)
                  <input type="range" min="8" max="30" value={fpsTarget}
                    onChange={(e) => setFpsTarget(Number(e.target.value))} />
                </label>
                <label className="field">
                  음성 안내
                  <select value={voice ? '1' : '0'} onChange={(e) => setVoice(e.target.value === '1')}>
                    <option value="1">켜기</option>
                    <option value="0">끄기</option>
                  </select>
                </label>
              </div>

              <button className="btn primary" style={{ marginTop: 12, width: '100%' }}
                disabled={corners.length !== 4} onClick={startLive}>
                판정 시작
              </button>
            </div>
          )}

          {(phase === 'live' || phase === 'done') && (
            <>
              {call && (
                <div className={`callbanner ${call.tooClose ? 'unknown' : call.kind}`}>
                  <span>{call.announce}</span>
                  <span className="small mono">
                    ±{call.errorBudgetCm}cm · 확신 {Math.round(call.confidence * 100)}%
                  </span>
                </div>
              )}

              {score && <Scoreboard score={score} />}

              <div className="row wrap">
                <button className="btn sm" onClick={() => send({ type: 'undo' })}>↩︎ 되돌리기</button>
                <button className="btn sm" onClick={() => send({ type: 'award', side: 'near' })}>니어 득점</button>
                <button className="btn sm" onClick={() => send({ type: 'award', side: 'far' })}>파 득점</button>
                <button className="btn sm" onClick={() => send({ type: 'serveNumber', value: 2 })}>세컨 서브</button>
                <span className="spacer" />
                <button className="btn sm danger" onClick={finish}>경기 종료 · 저장</button>
              </div>

              <div className="card tight">
                <div className="row small muted">
                  <span>화면 {stats.fps}fps</span>
                  <span>전송 {stats.sent}장</span>
                  <span className="spacer" />
                  <label className="row small" style={{ gap: 5 }}>
                    <input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)}
                      style={{ width: 'auto' }} />
                    음성
                  </label>
                </div>
              </div>

              <div className="card">
                <h3>진행 로그</h3>
                <div className="log">
                  {log.map((l, i) => <div key={i} className="line">{l}</div>)}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

function Scoreboard({ score }) {
  const names = score.names || {}
  const games = score.games || []
  const rows = ['A', 'B']
  return (
    <div className="scoreboard">
      {rows.map((k) => (
        <React.Fragment key={k}>
          <div className="name">
            {score.server === k && <span className="serve-dot" />}
            {names[k] || k}
            <span className="muted small">{score.ends?.[k] === 'near' ? '니어' : '파'}</span>
          </div>
          <div className="row" style={{ gap: 10 }}>
            {games.map((g, i) => <span key={i} className="mono muted">{g[k]}</span>)}
            <span className="pts">{score.points?.[k]}</span>
          </div>
        </React.Fragment>
      ))}
      <div className="small muted" style={{ gridColumn: '1 / -1' }}>
        {score.inTiebreak ? `타이브레이크 (${score.tiebreakTarget}점)` : ''}
        {score.serveNumber === 2 ? ' · 세컨 서브' : ''}
        {score.pressure?.breakPoint ? ' · 브레이크 포인트' : ''}
        {score.pressure?.setPoint ? ' · 세트 포인트' : ''}
        {score.pressure?.matchPoint ? ' · 매치 포인트' : ''}
      </div>
    </div>
  )
}

// ---------- 캔버스 오버레이 ----------
function drawOverlay(ctx, state, phase) {
  const { overlay, trail, lastCall, corners } = state

  if (overlay?.length) {
    ctx.strokeStyle = 'rgba(214,242,74,0.85)'
    ctx.lineWidth = 2
    ctx.beginPath()
    for (const [a, b] of overlay) {
      ctx.moveTo(a[0], a[1])
      ctx.lineTo(b[0], b[1])
    }
    ctx.stroke()
  }

  if (phase === 'calibrate' && corners?.length) {
    ctx.fillStyle = '#d6f24a'
    ctx.strokeStyle = '#d6f24a'
    ctx.lineWidth = 2
    corners.forEach(([x, y], i) => {
      ctx.beginPath()
      ctx.arc(x, y, 9, 0, Math.PI * 2)
      ctx.fill()
      ctx.fillStyle = '#0b1220'
      ctx.font = 'bold 13px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(i + 1), x, y + 1)
      ctx.fillStyle = '#d6f24a'
    })
    if (corners.length > 1) {
      ctx.beginPath()
      ctx.moveTo(corners[0][0], corners[0][1])
      corners.slice(1).forEach(([x, y]) => ctx.lineTo(x, y))
      if (corners.length === 4) ctx.closePath()
      ctx.stroke()
    }
  }

  if (trail?.length > 1) {
    for (let i = 1; i < trail.length; i++) {
      const alpha = i / trail.length
      ctx.strokeStyle = `rgba(56,189,248,${alpha * 0.9})`
      ctx.lineWidth = 1 + alpha * 2.5
      ctx.beginPath()
      ctx.moveTo(trail[i - 1][0], trail[i - 1][1])
      ctx.lineTo(trail[i][0], trail[i][1])
      ctx.stroke()
    }
    const [x, y] = trail[trail.length - 1]
    ctx.fillStyle = '#d6f24a'
    ctx.beginPath()
    ctx.arc(x, y, 5, 0, Math.PI * 2)
    ctx.fill()
  }

  if (lastCall) {
    const [x, y] = lastCall.image
    const color = lastCall.tooClose ? '#fbbf24' : (lastCall.kind === 'in' ? '#4ade80' : '#fb7185')
    ctx.strokeStyle = color
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.arc(x, y, 16, 0, Math.PI * 2)
    ctx.stroke()
    ctx.fillStyle = color
    ctx.font = 'bold 20px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'bottom'
    ctx.fillText(
      lastCall.tooClose ? '판독 불가' : (lastCall.kind === 'in' ? 'IN' : lastCall.kind.toUpperCase()),
      x + 22, y - 6,
    )
  }
}
