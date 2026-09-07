// 기본 활동 라이브러리.
// hp / mp = 강도 5(보통)에서의 "시간당" 소모량. 음수면 회복형 활동.
// phys/ment/soc/emo = 0~10 부하 성격(추천·컨텍스트 보정에 사용)
// rec = 회복 비용(0 낮음 ~ 1 높음), dur = 대표 시간(분), out = 산출물 기록 대상

export const CATEGORIES = [
  { id: "exercise", name: "운동", emoji: "💪" },
  { id: "work", name: "일·공부", emoji: "🧠" },
  { id: "social", name: "사회", emoji: "👥" },
  { id: "life", name: "생활", emoji: "🧺" },
  { id: "recover", name: "회복", emoji: "🌙" }
];

const A = (id, emoji, name, cat, hp, mp, phys, ment, soc, emo, rec, dur, out = false) => ({
  id, emoji, name, cat, hp, mp, phys, ment, soc, emo, rec, dur, out, builtin: true
});

export const BUILTIN_ACTIVITIES = [
  // 운동
  A("tennis", "🎾", "테니스", "exercise", 15, 7, 9, 6, 5, 6, 0.8, 90),
  A("gym", "🏋️", "웨이트", "exercise", 14, 4, 9, 3, 1, 2, 0.75, 60),
  A("run", "🏃", "러닝", "exercise", 13, 3, 9, 2, 0, 2, 0.55, 45),
  A("zone2", "🚴", "Zone2 유산소", "exercise", 6, 2, 5, 2, 0, 1, 0.25, 60),
  A("swim", "🏊", "수영", "exercise", 12, 3, 8, 2, 1, 1, 0.5, 45),
  A("hike", "🥾", "등산", "exercise", 16, 4, 9, 3, 2, 2, 0.9, 180),
  A("yoga", "🧘", "요가·스트레칭", "exercise", -2, -4, 3, 2, 0, 0, 0.05, 30),
  A("walk", "🚶", "산책", "exercise", -1, -5, 2, 1, 0, 0, 0.05, 25),

  // 일·공부
  A("deepwork", "💻", "딥워크", "work", 2, 12, 1, 9, 0, 3, 0.5, 90, true),
  A("coding", "⌨️", "코딩(일반)", "work", 2, 9, 1, 8, 1, 2, 0.4, 90, true),
  A("paper", "📄", "논문 읽기", "work", 1, 10, 1, 9, 0, 2, 0.35, 60, true),
  A("study", "📚", "공부·문제풀이", "work", 1, 10, 1, 9, 0, 3, 0.4, 60, true),
  A("writing", "✍️", "글쓰기", "work", 1, 11, 1, 9, 0, 4, 0.45, 90, true),
  A("class", "🎓", "수업 듣기", "work", 3, 8, 2, 7, 3, 2, 0.3, 90),
  A("teach", "🗣️", "발표·강의하기", "work", 5, 13, 4, 8, 7, 7, 0.8, 60),
  A("meeting", "👥", "회의", "work", 2, 9, 1, 6, 7, 4, 0.45, 60),
  A("lab", "🔬", "실험·데이터 수집", "work", 5, 9, 5, 7, 3, 3, 0.5, 120, true),
  A("chores_work", "📮", "이메일·잡무", "work", 1, 6, 1, 4, 3, 2, 0.15, 30),

  // 사회
  A("friends", "🍻", "친구 만나기", "social", 4, 9, 3, 4, 8, 5, 0.5, 120),
  A("family", "🏡", "가족 시간", "social", 2, 4, 2, 3, 5, 3, 0.2, 90),
  A("date", "💞", "데이트", "social", 3, 7, 3, 4, 7, 6, 0.4, 150),
  A("networking", "🎉", "행사·네트워킹", "social", 5, 13, 4, 6, 10, 8, 0.85, 150),
  A("call", "📞", "통화", "social", 1, 5, 0, 3, 6, 3, 0.15, 20),

  // 생활
  A("commute", "🚇", "이동·통근", "life", 3, 5, 4, 2, 3, 2, 0.25, 40),
  A("housework", "🧹", "집안일", "life", 5, 3, 6, 2, 0, 1, 0.2, 40),
  A("errand", "🛒", "장보기·심부름", "life", 4, 4, 5, 3, 3, 1, 0.2, 45),
  A("cook", "🍳", "요리", "life", 3, 4, 4, 4, 1, 1, 0.15, 40),
  A("admin", "🏥", "병원·행정", "life", 3, 8, 3, 5, 5, 6, 0.5, 60),

  // 회복 / 소비성 여가
  A("nap", "😴", "낮잠", "recover", -12, -16, 0, 0, 0, 0, 0, 30),
  A("meditate", "🧘‍♀️", "명상", "recover", -3, -9, 0, 1, 0, 0, 0, 15),
  A("audio", "🎧", "음악·오디오북", "recover", -2, -6, 0, 1, 0, 0, 0, 30),
  A("bath", "🛁", "목욕·사우나", "recover", -8, -8, 1, 0, 0, 0, 0, 30),
  A("movie", "🎬", "영화·드라마", "recover", 0, 1, 0, 2, 1, 3, 0.05, 120),
  A("game", "🎮", "게임", "recover", 1, 5, 1, 5, 3, 5, 0.2, 60),
  A("sns", "📱", "유튜브·SNS", "recover", 0, 3, 0, 3, 2, 3, 0.1, 30)
];

export const RECOVERY_LABEL = (rec) => (rec <= 0.2 ? "낮음" : rec <= 0.55 ? "중간" : "높음");
