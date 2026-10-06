import { useEffect, useState } from "react";
import { api, type Case, type PartChoices, type PartSlot } from "./api";

const SLOT_JA: Record<PartSlot, string> = { ears: "耳", tail: "尾", wings: "翼", horns: "角" };
const SHAPE_JA: Record<string, string> = {
  cat: "猫", fox: "狐", rabbit: "兎", devil: "悪魔", bat: "蝙蝠", feather: "羽毛", angel: "天使", none: "なし",
};
const ANATOMY_JA: Record<string, string> = { animal_ears: "獣の耳（人の耳を描かない）", tail: "尾（尾てい骨から）", wings: "翼（肩甲骨から）" };
// 部品を選んだら、その部品の体の決まりも入れる（耳を付けたのに人の耳が残る、を防ぐ）
const ANATOMY_OF: Partial<Record<PartSlot, string>> = { ears: "animal_ears", tail: "tail", wings: "wings" };
const NAME = /^[a-z0-9][a-z0-9_-]{0,40}$/;
const SLOTS: PartSlot[] = ["ears", "tail", "wings", "horns"];

type Props = { name: string; initial: Case; isNew: boolean; onSaved: (name: string) => void; onCancel: () => void };

export default function CaseForm({ name: initialName, initial, isNew, onSaved, onCancel }: Props) {
  const [choices, setChoices] = useState<PartChoices | null>(null);
  const [name, setName] = useState(initialName);
  const [c, setC] = useState<Case>(initial);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<{ id: string; files: string[] } | null>(null);
  const [shooting, setShooting] = useState(false);

  useEffect(() => {
    api.parts().then(setChoices).catch((e: Error) => setErrors([e.message]));
  }, []);

  const set = <K extends keyof Case>(key: K, value: Case[K]) => setC((prev) => ({ ...prev, [key]: value }));

  const setShape = (slot: PartSlot, shape: string) =>
    setC((prev) => {
      const parts = { ...(prev.parts ?? {}) };
      if (shape) parts[slot] = shape;
      else delete parts[slot];
      const anatomy = new Set(prev.anatomy ?? []);
      const rule = ANATOMY_OF[slot];
      if (rule && shape) anatomy.add(rule);
      return { ...prev, parts, anatomy: [...anatomy] };
    });

  const setPartColor = (slot: PartSlot, color: string) =>
    setC((prev) => ({ ...prev, parts: { ...(prev.parts ?? {}), color: { ...(prev.parts?.color ?? {}), [slot]: color } } }));

  const toggleAnatomy = (key: string) =>
    setC((prev) => {
      const a = new Set(prev.anatomy ?? []);
      if (a.has(key)) a.delete(key);
      else a.add(key);
      return { ...prev, anatomy: [...a] };
    });

  // 空の値は送らない。parts が空なら付けない（kind だけの種を壊さない）
  const cleaned = (): Case => {
    const out: Case = { ...c };
    if (out.parts && SLOTS.every((s) => !out.parts?.[s])) delete out.parts;
    if (!out.kind) delete out.kind;
    for (const k of ["ja", "negative", "background", "hair_color"] as const) if (!out[k]) delete out[k];
    return out;
  };

  const showErrors = (e: Error) => {
    // 設定の誤りは配列で返る（demi.validate_case）
    try {
      const parsed: unknown = JSON.parse(e.message);
      setErrors(Array.isArray(parsed) ? parsed.map(String) : [e.message]);
    } catch {
      setErrors([e.message]);
    }
  };

  const shoot = () => {
    setShooting(true);
    setErrors([]);
    api
      .preview(cleaned())
      .then(setPreview)
      .catch(showErrors)
      .finally(() => setShooting(false));
  };

  const save = () => {
    if (!NAME.test(name)) {
      setErrors(["名前は英小文字・数字・- _ で 41 字まで（先頭は英小文字か数字）"]);
      return;
    }
    const out = cleaned();
    setSaving(true);
    setErrors([]);
    api
      .saveCase(name, out)
      .then(() => onSaved(name))
      .catch(showErrors)
      .finally(() => setSaving(false));
  };

  const input = "w-full rounded border border-line bg-ink px-2 py-1";
  return (
    <div className="rounded border border-accent/60 bg-panel p-4">
      <h3 className="mb-3 font-bold">{isNew ? "新しい種" : `「${initial.ja ?? initialName}」を直す`}</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          名前（英小文字）
          <input className={input} value={name} disabled={!isNew} onChange={(e) => setName(e.target.value)} placeholder="wolfgirl" />
        </label>
        <label className="text-sm">
          表示名
          <input className={input} value={c.ja ?? ""} onChange={(e) => set("ja", e.target.value)} placeholder="狼娘" />
        </label>
      </div>

      <fieldset className="mt-4">
        <legend className="text-sm font-bold">部品（形と色）</legend>
        <div className="mt-1 grid gap-2 sm:grid-cols-2">
          {SLOTS.map((slot) => (
            <div key={slot} className="flex items-center gap-2">
              <span className="w-6 text-sm">{SLOT_JA[slot]}</span>
              <select
                className="flex-1 rounded border border-line bg-ink px-2 py-1"
                value={c.parts?.[slot] ?? ""}
                onChange={(e) => setShape(slot, e.target.value)}
                aria-label={`${SLOT_JA[slot]}の形`}
              >
                <option value="">なし</option>
                {(choices?.shapes[slot] ?? []).map((s) => (
                  <option key={s} value={s}>{SHAPE_JA[s] ?? s}</option>
                ))}
              </select>
              <input
                type="color"
                className="h-8 w-10 rounded border border-line bg-ink"
                disabled={!c.parts?.[slot]}
                value={c.parts?.color?.[slot] ?? "#222222"}
                onChange={(e) => setPartColor(slot, e.target.value)}
                aria-label={`${SLOT_JA[slot]}の色`}
              />
            </div>
          ))}
        </div>
        <label className="mt-2 block text-sm">
          3D の部品の組（部品を選んだ所はそちらが優先）
          <select className="ml-2 rounded border border-line bg-ink px-2 py-1" value={c.kind ?? ""} onChange={(e) => set("kind", e.target.value || undefined)}>
            <option value="">使わない</option>
            {(choices?.kinds ?? []).map((k) => (
              <option key={k} value={k}>{SHAPE_JA[k] ?? k}</option>
            ))}
          </select>
        </label>
      </fieldset>

      <fieldset className="mt-4">
        <legend className="text-sm font-bold">体の決まり</legend>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {(choices?.anatomy ?? []).map((a) => (
            <label key={a} className="text-sm">
              <input type="checkbox" className="mr-1 accent-accent" checked={c.anatomy?.includes(a) ?? false} onChange={() => toggleAnatomy(a)} />
              {ANATOMY_JA[a] ?? a}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-4 grid gap-3">
        <label className="text-sm">
          描く言葉（種の特徴、英語）
          <textarea className={input} rows={2} value={c.tags ?? ""} onChange={(e) => set("tags", e.target.value)} placeholder="wolf girl, grey wolf ears, fluffy grey wolf tail" />
        </label>
        <label className="text-sm">
          髪と目（英語）
          <input className={input} value={c.hair ?? ""} onChange={(e) => set("hair", e.target.value)} placeholder="silver hair, long twintails, blue eyes" />
        </label>
        <label className="text-sm">
          打ち消し（描かせないもの、英語）
          <textarea className={input} rows={2} value={c.negative ?? ""} onChange={(e) => set("negative", e.target.value)} placeholder="hairband, fake animal ears, multiple tails" />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
        <label>
          下絵の髪の色
          <input type="color" className="ml-2 h-8 w-10 rounded border border-line bg-ink align-middle" value={c.hair_color ?? "#222222"} onChange={(e) => set("hair_color", e.target.value)} />
        </label>
        <label>
          背景
          <input type="color" className="ml-2 h-8 w-10 rounded border border-line bg-ink align-middle" value={c.background ?? "#ffffff"} onChange={(e) => set("background", e.target.value)} />
        </label>
        <label>
          下絵から離れる強さ {c.strength ?? 0.6}
          <input type="range" min={0.1} max={0.95} step={0.05} className="ml-2 align-middle accent-accent" value={c.strength ?? 0.6} onChange={(e) => set("strength", Number(e.target.value))} />
        </label>
      </div>
      <p className="mt-1 text-xs text-neutral-400">白い部品（兎の耳、天使の羽）は白い背景に溶けて検品で消えたと数えられるので、背景を薄い灰にする</p>

      <div className="mt-4">
        <button type="button" onClick={shoot} disabled={shooting} className="rounded border border-line px-3 py-1.5 text-sm disabled:opacity-40">
          {shooting ? "3D の下絵を撮っています（約30秒）" : "3D の下絵を見る"}
        </button>
        <span className="ml-2 text-xs text-neutral-400">描く前に、部品の付け根（耳は頭の上、尾は尾てい骨、翼は肩甲骨）を4方向で見る</span>
        {preview && (
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {preview.files.includes("underlay.png") && (
              <img className="w-full rounded bg-white" src={api.previewUrl(preview.id, "underlay.png")} alt="3D の下絵（正面・斜め前・斜め後ろ・背面）" />
            )}
            {preview.files.includes("mask.png") && (
              <figure>
                <img className="w-full rounded" src={api.previewUrl(preview.id, "mask.png")} alt="部品の型（検品で数える場所）" />
                <figcaption className="mt-1 text-xs text-neutral-400">検品で数える場所: 緑 肌 / 赤 尾 / 紫 翼 / 黄 頭の部品</figcaption>
              </figure>
            )}
          </div>
        )}
      </div>

      {errors.length > 0 && (
        <ul className="mt-3 list-inside list-disc text-sm text-signal">
          {errors.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      <div className="mt-4 flex gap-3">
        <button type="button" onClick={save} disabled={saving} className="rounded bg-accent px-4 py-1.5 font-bold text-ink disabled:opacity-40">
          {saving ? "保存中" : "保存"}
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-line px-4 py-1.5">やめる</button>
      </div>
    </div>
  );
}
