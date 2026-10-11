import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type Layout, type LayoutNode, type LlmStatus, type PartChoices } from "./api";
import LayoutView from "./Layout";
import { type Ctx, type Pick, useRoles } from "./panels";

// 描いている間だけ短い間隔で聞く。描き終わったら聞かない（1枚 約3分かかるので、それより細かく見ても変わらない）
const POLL_MS = 5000;
const NARROW = 768;

// 配置の木の path の位置にある split の比率を置き換えた写しを返す
function withSizes(node: LayoutNode, path: number[], sizes: number[]): LayoutNode {
  if (!path.length) return node.type === "split" ? { ...node, sizes } : node;
  if (node.type === "panel") return node;
  const [k, ...rest] = path;
  return { ...node, children: node.children.map((c, i) => (i === k ? withSizes(c, rest, sizes) : c)) } as LayoutNode;
}

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [labels, setLabels] = useState<PartChoices | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [selected, setSelected] = useState<Pick | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [narrow, setNarrow] = useState(window.innerWidth < NARROW);
  const roles = useRoles();
  const saving = useRef<Layout | null>(null);

  const refreshJobs = useCallback(() => {
    api.jobs().then(setJobs).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    refreshJobs();
    api.parts().then(setLabels).catch(() => setLabels(null));   // 向きと部品の日本語名。無くても英語名で出る
    api.llm().then(setLlm).catch(() => setLlm(null));
    api.layout().then(setLayout).catch(() => setLayout(null));
    const onResize = () => setNarrow(window.innerWidth < NARROW);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [refreshJobs]);

  const busy = jobs.some((j) => j.state !== "done" && j.state !== "failed");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => {
      refreshJobs();
      setNow(Date.now());
    }, POLL_MS);
    return () => clearInterval(t);
  }, [busy, refreshJobs]);

  // 仕切りを動かしている間は画面だけ変え、離したときに保存する
  const onSizes = (path: number[], sizes: number[], done: boolean) => {
    setLayout((l) => {
      if (!l) return l;
      const next = { ...l, root: withSizes(l.root, path, sizes) };
      saving.current = next;
      return next;
    });
    if (done && saving.current) api.saveLayout(saving.current).catch((e: Error) => setError(`配置を保存できない: ${e.message}`));
  };

  const ctx: Ctx = { jobs, refreshJobs, selected, select: setSelected, llm, setLlm, roles, setError, now, labels };

  return (
    <main className={`mx-auto flex flex-col px-3 py-3 ${narrow ? "" : "h-screen"}`}>
      <header className="mb-2 flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-bold tracking-wide">
          Character<span className="text-accent">Designer</span> <span className="text-sm font-normal text-neutral-400">スタジオ</span>
        </h1>
        {layout?.notes?.map((n) => <span key={n} className="text-xs text-signal">{n}</span>)}
        {!narrow && (
          <button type="button" className="ml-auto text-xs underline" onClick={() => api.resetLayout().then(setLayout).catch((e: Error) => setError(e.message))}>
            配置を既定に戻す
          </button>
        )}
      </header>
      {error && <p className="mb-2 rounded border border-signal p-2 text-sm text-signal">{error}</p>}
      <div className={narrow ? "" : "min-h-0 flex-1"}>
        {layout ? <LayoutView root={layout.root} ctx={ctx} narrow={narrow} onSizes={onSizes} /> : <p className="text-sm text-neutral-400">配置を読んでいる…</p>}
      </div>
    </main>
  );
}
