import { useEffect, useState } from "react";
import type { Ctx } from "./panels";
import { currentRef, setRef, type RefPick } from "./refs";

// 参考画像。探して手元に置き、1枚を「描くときに使う」にすると、描く依頼に画風と色の手本として添える。
// 探す先は CC ライセンスと public domain の画像（Openverse）。作者・ライセンス・元のページを必ず一緒に見せる
type Hit = { id: string; title: string; url: string; thumb: string; creator: string; license: string; license_version: string;
  license_url: string; landing: string; source: string };
type Saved = Omit<Hit, "thumb"> & { file: string };

const lic = (h: { license: string; license_version: string }) => `CC ${h.license.toUpperCase()} ${h.license_version}`.replace("CC PDM", "Public Domain").replace("CC CC0", "CC0").trim();

export default function RefsPanel({ ctx }: { ctx: Ctx }) {
  const [q, setQ] = useState("");
  const [commercial, setCommercial] = useState(false);
  const [hits, setHits] = useState<Hit[]>([]);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [busy, setBusy] = useState("");
  const [pick, setPick] = useState<RefPick | null>(currentRef);

  const load = () => fetch("/api/refs").then((r) => r.json()).then((j: { refs: Saved[] }) => setSaved(j.refs)).catch(() => setSaved([]));
  useEffect(() => {
    load();
    const on = () => setPick(currentRef());
    window.addEventListener("cd-ref", on);
    return () => window.removeEventListener("cd-ref", on);
  }, []);

  const search = async () => {
    setBusy("探しています");
    try {
      const r = await fetch(`/api/refs/search?${new URLSearchParams({ q, n: "16", commercial: String(commercial) })}`);
      if (!r.ok) throw new Error((await r.json()).detail ?? `探せなかった（${r.status}）`);
      setHits(((await r.json()) as { results: Hit[] }).results);
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const keep = async (h: Hit) => {
    setBusy("手元に置いています");
    try {
      const r = await fetch("/api/refs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(h) });
      if (!r.ok) throw new Error((await r.json()).detail ?? `置けなかった（${r.status}）`);
      await load();
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const use = (s: Saved | null, scale = pick?.scale ?? 0.5) => setRef(s ? { id: s.id, scale, title: s.title } : null);

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-neutral-400">
        CC ライセンスと public domain の画像を探す。描くときに使う1枚を選ぶと、スタジオと自由に描くの依頼に画風と色の手本として添える。
        使う条件（作者の表示、非営利など）は元のページで確かめる。手元に置いた画像は <code>.cache/app/refs</code> にあり、リポジトリには入れない。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input className="min-w-0 flex-1 rounded border border-line bg-transparent px-2 py-0.5" placeholder="探す言葉（英語が多く当たる。例: knight armor）"
          value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q.trim() && search()} />
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={commercial} onChange={(e) => setCommercial(e.target.checked)} />営利で使えるものだけ</label>
        <button type="button" className="rounded bg-accent px-3 py-0.5 text-xs font-bold text-ink" disabled={!q.trim() || !!busy} onClick={search}>探す</button>
        {busy && <span className="text-xs text-neutral-400">{busy}…</span>}
      </div>
      {hits.length > 0 && (
        <ul className="grid grid-cols-3 gap-2">
          {hits.map((h) => (
            <li key={h.id} className="rounded border border-line p-1 text-xs">
              <img src={h.thumb} alt={h.title || "参考画像の候補"} className="h-24 w-full object-cover" loading="lazy" referrerPolicy="no-referrer" />
              <p className="truncate" title={h.title}>{h.title || "（題名なし）"}</p>
              <p className="truncate text-neutral-400">{h.creator || "作者不明"} / {lic(h)}</p>
              <div className="flex gap-1">
                <button type="button" className="rounded border border-line px-1" disabled={!!busy} onClick={() => keep(h)}>手元に置く</button>
                {h.landing && <a className="underline" href={h.landing} target="_blank" rel="noreferrer">元のページ</a>}
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2 text-xs">
        <span className="font-bold">描くときに使う:</span>
        <span>{pick ? pick.title || pick.id : "使わない"}</span>
        {pick && (
          <>
            <label className="flex items-center gap-1">効かせる強さ
              <input type="range" min={0.1} max={1} step={0.05} value={pick.scale} onChange={(e) => setRef({ ...pick, scale: +e.target.value })} />
              {Math.round(pick.scale * 100)}%</label>
            <button type="button" className="underline" onClick={() => use(null)}>使わない</button>
          </>
        )}
      </div>
      {saved.length > 0 && (
        <ul className="grid grid-cols-4 gap-2">
          {saved.map((s) => (
            <li key={s.id} className={`rounded border p-1 text-xs ${pick?.id === s.id ? "border-accent" : "border-line"}`}>
              <img src={`/api/refs/file/${s.id}`} alt={s.title || "手元に置いた参考画像"} className="h-20 w-full object-cover" />
              <p className="truncate" title={`${s.title} / ${s.creator} / ${lic(s)}`}>{s.creator || "作者不明"} / {lic(s)}</p>
              <button type="button" className="rounded border border-line px-1" onClick={() => use(s)}>{pick?.id === s.id ? "使っている" : "描くときに使う"}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
