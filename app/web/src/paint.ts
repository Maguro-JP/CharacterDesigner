// 描く板の計算（画面から切り離す。線の補正と太さの決め方だけを持つ）

export type Pt = { x: number; y: number; p: number };

// 筆圧から太さを決める。min は筆圧 0 のときの太さの割合（既定 0.2: かすれて消えないように最小でも 2 割は残す）
export function widthOf(size: number, pressure: number, usePressure: boolean, min = 0.2): number {
  if (!usePressure) return size;
  const p = Math.min(1, Math.max(0, pressure || 0.5));
  return size * (min + (1 - min) * p);
}

// 補助の設定。どれも描く人が入れ切りと強さを決める（補正が効きすぎて表現が消えるのを嫌う人がいるため）
export type Assist = {
  steady: boolean; steadyAmount: number;     // 手ぶれ補正（描いている間、ペン先を後追いさせる）
  round: boolean; roundPasses: number;       // 離したときに角を丸める回数
  taper: boolean; taperAmount: number;       // 離したときに頭と尻を細くする量
  pressure: boolean; pressureMin: number;    // 筆圧で太さを変える。min は筆圧 0 のときの太さの割合
  inkMerge: number; inkSpur: number; inkWidth: number; // 線の清書: まとめる幅、落とすひげの長さ、太さ（ペンの太さに掛ける）
};
export const ASSIST_DEFAULT: Assist = {
  steady: true, steadyAmount: 0.5, round: true, roundPasses: 2, taper: true, taperAmount: 0.15,
  pressure: true, pressureMin: 0.2, inkMerge: 3, inkSpur: 6, inkWidth: 0.6,
};
// 全部切る: 描いたとおりの線をそのまま残す
export const ASSIST_OFF: Assist = { ...ASSIST_DEFAULT, steady: false, round: false, taper: false, pressure: false };

const KEY = "cd.paint.assist";
export function loadAssist(): Assist {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return v && typeof v === "object" ? { ...ASSIST_DEFAULT, ...v } : ASSIST_DEFAULT;
  } catch {
    return ASSIST_DEFAULT;
  }
}
export function saveAssist(a: Assist) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* 覚えられなくても描ける */
  }
}

// 離したときの線に補助を掛ける。切ってあるものは掛けない
export function finishStroke(pts: Pt[], a: Assist): Pt[] {
  let out = pts;
  if (a.round && a.roundPasses > 0) out = smooth(out, a.roundPasses);
  if (a.taper && a.taperAmount > 0) out = taper(out, a.taperAmount);
  return out;
}

// 手ぶれ補正（後追い）。ペン先を紐で引くように、入力の点へ少しずつ寄せる。strength 0 で補正なし、0.9 で強い
export function follow(prev: Pt, next: Pt, strength: number): Pt {
  const k = 1 - Math.min(0.95, Math.max(0, strength));
  return { x: prev.x + (next.x - prev.x) * k, y: prev.y + (next.y - prev.y) * k, p: prev.p + (next.p - prev.p) * k };
}

// 線を整える: 角を丸める（Chaikin の切り落としを n 回）。始点と終点は動かさない
export function smooth(pts: Pt[], n = 2): Pt[] {
  let cur = pts;
  for (let r = 0; r < n && cur.length > 2; r++) {
    const out: Pt[] = [cur[0] as Pt];
    for (let i = 0; i < cur.length - 1; i++) {
      const a = cur[i] as Pt, b = cur[i + 1] as Pt;
      out.push({ x: a.x * 0.75 + b.x * 0.25, y: a.y * 0.75 + b.y * 0.25, p: a.p * 0.75 + b.p * 0.25 });
      out.push({ x: a.x * 0.25 + b.x * 0.75, y: a.y * 0.25 + b.y * 0.75, p: a.p * 0.25 + b.p * 0.75 });
    }
    out.push(cur[cur.length - 1] as Pt);
    cur = out;
  }
  return cur;
}

// 入り抜き: 線の頭と尻を細くする。taper は線の長さに対する割合（0 で無し）。手描きの線らしい強弱を付ける
export function taper(pts: Pt[], amount: number): Pt[] {
  if (amount <= 0 || pts.length < 3) return pts;
  const len: number[] = [0];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1] as Pt, b = pts[i] as Pt;
    len.push((len[i - 1] as number) + Math.hypot(b.x - a.x, b.y - a.y));
  }
  const total = len[len.length - 1] as number;
  if (total === 0) return pts;
  const span = total * Math.min(0.5, amount);
  return pts.map((q, i) => {
    const d = Math.min(len[i] as number, total - (len[i] as number));
    return { ...q, p: q.p * Math.min(1, 0.15 + 0.85 * (d / span)) };
  });
}

// 1本の線を、点ごとの太さで描く（隣の点を太さ付きの線分でつなぐ）
export function drawStroke(g: CanvasRenderingContext2D, pts: Pt[], size: number, usePressure: boolean, min = 0.2) {
  g.lineCap = "round";
  g.lineJoin = "round";
  if (pts.length === 1) {
    const q = pts[0] as Pt;
    g.beginPath();
    g.arc(q.x, q.y, widthOf(size, q.p, usePressure, min) / 2, 0, Math.PI * 2);
    g.fill();
    return;
  }
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1] as Pt, b = pts[i] as Pt;
    g.lineWidth = widthOf(size, (a.p + b.p) / 2, usePressure, min);
    g.beginPath();
    g.moveTo(a.x, a.y);
    g.lineTo(b.x, b.y);
    g.stroke();
  }
}

// 既定のパレット。白黒の階調、肌、髪、布でよく使う色。利用者の色は「最近使った色」に足していく
export const PRESET = [
  "#000000", "#3a3a3a", "#7a7a7a", "#bdbdbd", "#ffffff",
  "#f6d7c3", "#e8b896", "#c68863", "#8a5a3c", "#4a2f22",
  "#d62828", "#f77f00", "#fcbf49", "#2a9d8f", "#264653",
  "#3a86ff", "#8338ec", "#ff006e", "#6a994e", "#bc6c25",
];
