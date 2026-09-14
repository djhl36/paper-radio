// ── 음식 사진 → 영양 추정 ────────────────────────────────────────────
// 서버가 없는 앱이라, 사용자의 Anthropic API 키로 브라우저에서 직접 부른다.
// 키는 이 기기의 localStorage 에만 있고 어디로도 전송되지 않는다(Anthropic API 외).
// SDK 가 브라우저 직접 호출을 막아 두었으므로 dangerouslyAllowBrowser 로 명시적으로 연다.

export const FOOD_MODELS = [
  { id: "claude-opus-5", label: "Opus 5", hint: "가장 정확" },
  { id: "claude-sonnet-5", label: "Sonnet 5", hint: "빠르고 저렴" },
  { id: "claude-haiku-4-5", label: "Haiku 4.5", hint: "가장 저렴" }
];

const SYSTEM = `너는 식사 사진을 보고 영양을 어림하는 도우미다.
- 한국 가정식·배달·편의점 음식에 익숙하다고 가정한다.
- 정확한 계량은 불가능하므로 "대략"으로 답하되, 범위를 넓게 잡지 말고 하나의 값으로 답한다.
- 보이지 않는 것은 지어내지 않는다. 사진에 음식이 없으면 items 를 빈 배열로 둔다.
- 반드시 JSON 객체 하나만 출력한다. 설명 문장, 코드펜스, 주석을 붙이지 않는다.`;

const PROMPT = `이 사진의 식사를 판별해서 아래 JSON 형식으로만 답해줘.

{
  "items": ["음식 이름", ...],
  "kcal": 정수,
  "protein": 단백질 그램(정수),
  "carb": 탄수화물 그램(정수),
  "fat": 지방 그램(정수),
  "quality": 0 | 1 | 2,
  "note": "한 문장 코멘트"
}

quality 기준 — 0: 부실하다(단백질이 거의 없거나 열량만 높음), 1: 보통, 2: 잘 챙겼다(단백질·채소가 충분).`;

/** 휴대폰 사진은 크기 때문에 그대로 보내면 느리다. 긴 변 1024px, JPEG 로 줄인다. */
export function shrinkImage(file, maxSide = 1024, quality = 0.82) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("사진을 읽지 못했습니다."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("사진을 열지 못했습니다."));
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

const parseJSON = (text) => {
  const s = text.indexOf("{");
  const e = text.lastIndexOf("}");
  if (s < 0 || e <= s) throw new Error("응답을 이해하지 못했습니다.");
  return JSON.parse(text.slice(s, e + 1));
};

/**
 * @param apiKey  사용자의 Anthropic API 키
 * @param dataUrl shrinkImage 가 만든 data:image/jpeg;base64,...
 * @param model   FOOD_MODELS 중 하나
 */
export async function analyzeFoodPhoto({ apiKey, dataUrl, model = "claude-opus-5" }) {
  if (!apiKey) throw new Error("설정에서 Anthropic API 키를 먼저 넣어 주세요.");
  const m = String(dataUrl).match(/^data:([^;]+);base64,(.+)$/);
  if (!m) throw new Error("사진 형식을 읽지 못했습니다.");

  // SDK 는 사진을 볼 때만 필요하므로 그때 불러온다 (첫 화면 번들을 키우지 않기 위해)
  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey, dangerouslyAllowBrowser: true });
  const res = await client.messages.create({
    model,
    max_tokens: 1000,
    system: SYSTEM,
    // 단순 판별이라 얕게 생각해도 된다. effort 는 Haiku 4.5 에서 지원되지 않으므로 빼고 보낸다.
    ...(model.startsWith("claude-haiku") ? {} : { output_config: { effort: "low" } }),
    messages: [
      {
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: m[1], data: m[2] } },
          { type: "text", text: PROMPT }
        ]
      }
    ]
  });

  if (res.stop_reason === "refusal") throw new Error("이 사진은 판별할 수 없습니다.");
  const text = res.content.filter((b) => b.type === "text").map((b) => b.text).join("");
  const j = parseJSON(text);
  const num = (v) => (Number.isFinite(Number(v)) ? Math.round(Number(v)) : null);
  return {
    items: Array.isArray(j.items) ? j.items.slice(0, 8).map(String) : [],
    kcal: num(j.kcal),
    protein: num(j.protein),
    carb: num(j.carb),
    fat: num(j.fat),
    quality: [0, 1, 2].includes(Number(j.quality)) ? Number(j.quality) : 1,
    note: j.note ? String(j.note).slice(0, 120) : null,
    model,
    at: Date.now()
  };
}
