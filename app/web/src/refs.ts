// 描くときに使う参考画像（ひとつだけ）。参考画像の板で選び、描く依頼（スタジオ・自由に描く）に自動で添える。
// 選んでいなければ何も添えない。ブラウザに覚えさせる（覚えられなくても描ける）
export type RefPick = { id: string; scale: number; title: string };
const KEY = "cd.ref";

export function currentRef(): RefPick | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return v && typeof v.id === "string" && v.id ? v : null;
  } catch {
    return null;
  }
}

export function setRef(r: RefPick | null) {
  try {
    if (r) localStorage.setItem(KEY, JSON.stringify(r));
    else localStorage.removeItem(KEY);
  } catch {
    /* 覚えられなくても描ける */
  }
  window.dispatchEvent(new Event("cd-ref"));
}

// 依頼に添える分。依頼の側で ref を指定していればそちらを使う
export function withRef<T extends object>(body: T): T {
  const r = currentRef();
  if (!r || "ref" in body) return body;
  return { ...body, ref: r.id, ref_scale: r.scale };
}
