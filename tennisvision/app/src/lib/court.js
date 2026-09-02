// 코트 좌표(m) <-> 미니맵 SVG 좌표 변환과 그리기 데이터.
// 엔진의 engine/geometry.py 와 같은 규격을 쓴다.

export const HALF_LENGTH = 11.885
export const SINGLES_HALF_W = 4.115
export const DOUBLES_HALF_W = 5.485
export const SERVICE_LINE_Y = 6.4

// 미니맵은 세로로 긴 코트를 위에서 내려다본 모양.
export const MAP = { w: 220, h: 460, pad: 14 }

export function toMap(x, y, map = MAP) {
  const usableW = map.w - map.pad * 2
  const usableH = map.h - map.pad * 2
  return [
    map.pad + ((x + DOUBLES_HALF_W) / (DOUBLES_HALF_W * 2)) * usableW,
    map.pad + ((HALF_LENGTH - y) / (HALF_LENGTH * 2)) * usableH,
  ]
}

export const COURT_LINES = [
  // [x1,y1,x2,y2] (코트 좌표)
  [-DOUBLES_HALF_W, -HALF_LENGTH, DOUBLES_HALF_W, -HALF_LENGTH],
  [-DOUBLES_HALF_W, HALF_LENGTH, DOUBLES_HALF_W, HALF_LENGTH],
  [-DOUBLES_HALF_W, -HALF_LENGTH, -DOUBLES_HALF_W, HALF_LENGTH],
  [DOUBLES_HALF_W, -HALF_LENGTH, DOUBLES_HALF_W, HALF_LENGTH],
  [-SINGLES_HALF_W, -HALF_LENGTH, -SINGLES_HALF_W, HALF_LENGTH],
  [SINGLES_HALF_W, -HALF_LENGTH, SINGLES_HALF_W, HALF_LENGTH],
  [-SINGLES_HALF_W, -SERVICE_LINE_Y, SINGLES_HALF_W, -SERVICE_LINE_Y],
  [-SINGLES_HALF_W, SERVICE_LINE_Y, SINGLES_HALF_W, SERVICE_LINE_Y],
  [0, -SERVICE_LINE_Y, 0, SERVICE_LINE_Y],
]

export function inSingles(x, y) {
  return Math.abs(x) <= SINGLES_HALF_W && Math.abs(y) <= HALF_LENGTH
}

// 서브 코스 이름
export function serveZoneKo(zone) {
  return { T: '센터(T)', body: '바디', wide: '와이드' }[zone] || zone
}

export const SHOT_KO = {
  serve: '서브', return: '리턴', forehand: '포핸드', backhand: '백핸드',
  volley: '발리', overhead: '스매시', slice: '슬라이스', drop: '드롭샷', lob: '로브',
}

export const RESULT_KO = {
  in_play: '진행', winner: '위너', forced_error: '강요된 실책',
  unforced_error: '언포스드', ace: '에이스', double_fault: '더블폴트',
}

export const END_REASON_KO = {
  winner: '위너', ace: '에이스', double_bounce: '못 받음', out: '아웃',
  net: '네트', unforced_error: '실책', forced_error: '강요된 실책',
  double_fault: '더블폴트', manual: '수동 입력',
}

export const DIRECTION_KO = {
  cross: '크로스', down_the_line: '다운더라인', middle: '가운데',
}
