import { useEffect, useState } from "react";
import type { Ctx } from "./panels";

// 利用者のフィルター。描きたくないものを自分で止める。既定は全部切ってある（最初から規制はしない）。
// 設定で外せない制限（子どもを性的に描くこと）は、ここでは切れないことを一緒に見せる。説明は docs/filters.md
type Filter = { name: string; enabled: boolean; words: string[]; negative: string };

export default function FiltersPanel({ ctx }: { ctx: Ctx }) {
  const [fs, setFs] = useState<Filter[]>([]);
  const [fixed, setFixed] = useState("");
  const [saved, setSaved] = useState("");
  const [newName, setNewName] = useState("");

  useEffect(() => {
    fetch("/api/filters").then((r) => r.json()).then((j: { filters: Filter[]; fixed: string }) => {
      setFs(j.filters.map((f) => ({ ...f, words: f.words ?? [] })));
      setFixed(j.fixed);
    }).catch((e: Error) => ctx.setError(e.message));
  }, []);

  const patch = (i: number, p: Partial<Filter>) => { setFs((xs) => xs.map((f, k) => (k === i ? { ...f, ...p } : f))); setSaved(""); };
  const save = () =>
    fetch("/api/filters", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filters: fs }) })
      .then((r) => { if (!r.ok) throw new Error(`保存できなかった（${r.status}）`); return r.json(); })
      .then((j: { filters: Filter[] }) => { setFs(j.filters); setSaved("保存した"); })
      .catch((e: Error) => ctx.setError(e.message));

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-neutral-400">
        描く内容は最初から規制しない。描きたくないものを、ここで入れたフィルターで止める（頼みごとか描く言葉に、止める言葉が出たら描かない）。
        言葉はどの言語で書いてもよい。設定は <code>config/filters.json</code> に残る。
      </p>
      <p className="rounded border border-line p-2 text-xs">
        <span className="font-bold">外せない制限:</span> {fixed || "読み込み中"}
      </p>
      <ul className="space-y-2">
        {fs.map((f, i) => (
          <li key={i} className="rounded border border-line p-2">
            <label className="flex items-center gap-2 font-bold">
              <input type="checkbox" checked={f.enabled} onChange={(e) => patch(i, { enabled: e.target.checked })} />
              {f.name}
              <span className={`text-xs font-normal ${f.enabled ? "text-accent" : "text-neutral-400"}`}>{f.enabled ? "入れている" : "切っている"}</span>
              <button type="button" className="ml-auto text-xs text-neutral-400 underline" onClick={() => { setFs((xs) => xs.filter((_, k) => k !== i)); setSaved(""); }}>消す</button>
            </label>
            <label className="mt-1 block text-xs">止める言葉（カンマか改行で区切る）
              <textarea className="mt-0.5 w-full rounded border border-line bg-transparent p-1" rows={2} value={f.words.join(", ")}
                onChange={(e) => patch(i, { words: e.target.value.split(/[,、\n]/).map((w) => w.trim()).filter(Boolean) })} />
            </label>
            <label className="block text-xs">描かせない言葉に足す（任意）
              <input className="mt-0.5 w-full rounded border border-line bg-transparent p-1" value={f.negative} onChange={(e) => patch(i, { negative: e.target.value })} />
            </label>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <input className="rounded border border-line bg-transparent px-2 py-0.5 text-xs" placeholder="新しいフィルターの名前" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button type="button" className="rounded border border-line px-2 py-0.5 text-xs" disabled={!newName.trim()}
          onClick={() => { setFs((xs) => [...xs, { name: newName.trim(), enabled: true, words: [], negative: "" }]); setNewName(""); setSaved(""); }}>足す</button>
        <button type="button" className="ml-auto rounded bg-accent px-3 py-0.5 text-xs font-bold text-ink" onClick={save}>保存</button>
        {saved && <span className="text-xs text-accent">{saved}</span>}
      </div>
    </div>
  );
}
