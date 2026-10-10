import { useEffect, useState, type ReactNode } from "react";
import { api, type Job, type LlmStatus, type Memory, type PartChoices, type Proposal, type Role, type StudioIn } from "./api";
import DemiPanel from "./DemiPanel";
import { LlmSettings, readerJa } from "./FreePanel";
import JobCard from "./JobCard";

// 板が共有する状態。App が持ち、配置（Layout）がどこに板を置いても同じものを見る
export type Ctx = {
  jobs: Job[];
  refreshJobs: () => void;
  selected: Pick | null;
  select: (p: Pick) => void;
  llm: LlmStatus | null;
  setLlm: (s: LlmStatus) => void;
  roles: Role[];
  setError: (m: string) => void;
  now: number;
  labels: PartChoices | null;
};

// 描いた絵の1枚（どの仕事の、どのファイルか）
export type Pick = { jobId: string; file: string };

type Item = Pick & { label: string; passed: boolean; prompt: string; job: Job };

// 仕事から絵を拾う。スタジオは描いた順の全部（通ったものに印）、自由に描くは描けた絵、亜人は通った設定資料
export function galleryItems(jobs: Job[]): Item[] {
  const out: Item[] = [];
  for (const j of jobs) {
    if (j.kind === "studio") {
      const files = j.outcome?.files ?? (j.events ?? []).filter((e) => e.role === "PAINTER" && e.file).map((e) => e.file as string);
      files.forEach((f) => out.push({ jobId: j.id, file: f, label: j.case_name, passed: j.outcome?.passed === f, prompt: j.outcome?.prompt ?? "", job: j }));
    } else if (j.kind === "free") {
      j.results.forEach((r) => r.file && out.push({ jobId: j.id, file: r.file, label: j.case_name, passed: true, prompt: j.free?.prompt ?? "", job: j }));
    } else if (j.files.includes("sheet.png")) {
      out.push({ jobId: j.id, file: "sheet.png", label: j.case_name, passed: true, prompt: "", job: j });
    }
  }
  // 仕事は新しい順に来るので、そのまま新しい絵が先頭（「大きく見る」も既定で一番新しい絵を出す）
  return out.filter((i) => i.job.files.includes(i.file));
}

const SIZES: Record<StudioIn["size"], string> = { portrait: "縦長", landscape: "横長", square: "正方形" };

function PromptPanel({ ctx }: { ctx: Ctx }) {
  const [text, setText] = useState("");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [size, setSize] = useState<StudioIn["size"]>("portrait");
  const [tries, setTries] = useState(3);
  const [seed, setSeed] = useState(0);
  const [direct, setDirect] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  // 描く言葉を先に見たいとき。見なくても、頼めば読み手（INTERPRETER）が読む
  const preview = () => {
    setBusy(true);
    setNote("");
    api
      .freeDescribe(text)
      .then((r) => {
        setNote(`${readerJa(r.reader)}${r.summary ? `: ${r.summary}` : ""}${r.allowed ? "" : ` — ${r.reason}`}`);
        if (r.allowed) {
          setPrompt(r.prompt);
          setNegative(r.negative);
        }
      })
      .catch((e: Error) => ctx.setError(e.message))
      .finally(() => setBusy(false));
  };

  const submit = () => {
    ctx.setError("");
    api
      .studioSubmit({ text, prompt, negative, seed, size, tries, direct })
      .then(() => {
        ctx.refreshJobs();
        setSeed((s) => s + tries);   // 次は別の絵になるよう進める（同じ絵を描き直したければ戻せる）
      })
      .catch((e: Error) => ctx.setError(e.message));
  };

  return (
    <div className="space-y-2 text-sm">
      <LlmSettings status={ctx.llm} onChange={ctx.setLlm} />
      <textarea
        className="h-20 w-full rounded border border-line bg-ink px-2 py-1"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="赤いマフラーの騎士の少年、雪の城の前 など"
        aria-label="頼みごと"
        maxLength={200}
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!text.trim() || busy} onClick={preview} className="rounded border border-line px-3 py-1 disabled:opacity-40">
          {busy ? "読んでいる…" : "描く言葉を先に見る"}
        </button>
        <button type="button" disabled={!text.trim() && !prompt.trim()} onClick={submit} className="rounded bg-accent px-4 py-1 font-bold text-ink disabled:opacity-40">
          スタジオに頼む
        </button>
      </div>
      {note && <p className="text-xs text-neutral-400">{note}</p>}
      <label className="block">
        描く言葉（空なら読み手が頼みごとから作る）
        <textarea className="mt-1 h-20 w-full rounded border border-line bg-ink px-2 py-1 font-mono text-xs" value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="描く言葉" />
      </label>
      <label className="block">
        描かないもの
        <input className="mt-1 w-full rounded border border-line bg-ink px-2 py-1 font-mono text-xs" value={negative} onChange={(e) => setNegative(e.target.value)} aria-label="描かないもの" />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <select className="rounded border border-line bg-ink px-2 py-1" value={size} onChange={(e) => setSize(e.target.value as StudioIn["size"])} aria-label="形">
          {Object.entries(SIZES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label>
          描き直し
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={tries} onChange={(e) => setTries(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} 回まで</option>)}
          </select>
        </label>
        <label>
          seed
          <input type="number" min={0} className="ml-1 w-20 rounded border border-line bg-ink px-2 py-1" value={seed} onChange={(e) => setSeed(Math.max(0, Number(e.target.value) || 0))} />
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={direct} onChange={(e) => setDirect(e.target.checked)} />
          演出に構図と光を任せる
        </label>
      </div>
      <p className="text-xs text-neutral-400">CPU では1枚 約2〜3分。最初の1件は描く模型の読み込みに 約10分</p>
    </div>
  );
}

function CanvasPanel({ ctx }: { ctx: Ctx }) {
  const items = galleryItems(ctx.jobs);
  const cur = items.find((i) => ctx.selected && i.jobId === ctx.selected.jobId && i.file === ctx.selected.file) ?? items[0];
  const [notan, setNotan] = useState(false);
  if (!cur) return <p className="text-sm text-neutral-400">まだ描いた絵が無い。頼みごとを書いて「スタジオに頼む」</p>;
  const notanFile = cur.file.replace(".png", "-notan.png");
  const hasNotan = cur.job.files.includes(notanFile);
  const critique = cur.passed ? (cur.job.outcome?.critique ?? []) : [];
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-2 text-sm">
        <span className="font-bold">{cur.label}</span>
        {cur.job.kind === "studio" && <span className={cur.passed ? "text-accent" : "text-signal"}>{cur.passed ? "検品 通過" : "検品 不通過"}</span>}
        {hasNotan && (
          <button type="button" className="ml-auto underline" onClick={() => setNotan((n) => !n)}>
            {notan ? "絵に戻す" : "明暗の塊を見る"}
          </button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center rounded bg-black/30">
        <img className="max-h-full max-w-full object-contain" src={api.fileUrl(cur.jobId, notan && hasNotan ? notanFile : cur.file)} alt={`${cur.label} を大きく見る`} />
      </div>
      {cur.prompt && <p className="break-words font-mono text-xs text-neutral-400">{cur.prompt}</p>}
      {critique.map((c) => <p key={c} className="text-xs text-neutral-300">CRITIC: {c}</p>)}
    </div>
  );
}

function GalleryPanel({ ctx }: { ctx: Ctx }) {
  const items = galleryItems(ctx.jobs);
  if (!items.length) return <p className="text-sm text-neutral-400">まだ無い</p>;
  return (
    <ul className="flex gap-2 overflow-x-auto pb-1">
      {items.map((i) => {
        const on = ctx.selected?.jobId === i.jobId && ctx.selected?.file === i.file;
        return (
          <li key={`${i.jobId}/${i.file}`} className="shrink-0">
            <button type="button" onClick={() => ctx.select(i)} className={`block rounded border-2 ${on ? "border-accent" : i.passed ? "border-line" : "border-signal/60"}`}>
              <img className="h-28 w-auto rounded" src={api.fileUrl(i.jobId, i.file)} alt={`${i.label}（${i.file}）`} loading="lazy" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// 役割と出来事は、選んだ絵の仕事（無ければ一番新しいスタジオの仕事）を見る
function focusJob(ctx: Ctx): Job | undefined {
  return ctx.jobs.find((j) => j.id === ctx.selected?.jobId && j.kind === "studio") ?? ctx.jobs.find((j) => j.kind === "studio");
}

function RosterPanel({ ctx }: { ctx: Ctx }) {
  const job = focusJob(ctx);
  const last = (name: string) => [...(job?.events ?? [])].reverse().find((e) => e.role === name);
  return (
    <ul className="space-y-2 text-sm">
      {ctx.roles.map((r) => {
        const e = last(r.name);
        return (
          <li key={r.name} className="rounded border border-line p-2">
            <p>
              <span className="font-bold">{r.name}</span> <span className="text-neutral-400">{r.ja}</span>
              {e && <span className={`ml-2 text-xs ${e.stage === "fail" || e.stage === "stop" ? "text-signal" : "text-accent"}`}>{e.stage}</span>}
            </p>
            <p className="text-xs text-neutral-400">{r.temper}</p>
            {e && <p className="mt-1 text-xs">{e.msg}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function LogPanel({ ctx }: { ctx: Ctx }) {
  const job = focusJob(ctx);
  if (!job) return <p className="text-sm text-neutral-400">スタジオの仕事がまだ無い</p>;
  return (
    <ol className="space-y-1 text-xs">
      {(job.events ?? []).map((e, k) => (
        <li key={k}>
          <span className="text-neutral-500">{new Date(e.t * 1000).toLocaleTimeString("ja-JP")}</span>{" "}
          <span className="font-bold">{e.role}</span> <span className={e.stage === "fail" || e.stage === "stop" ? "text-signal" : ""}>{e.msg}</span>
        </li>
      ))}
      {job.outcome?.reason && <li className="text-signal">{job.outcome.reason}</li>}
    </ol>
  );
}

// 覚えていること。通った描く言葉は、似た頼みごとのときに読み手へ手本として添えられる
function MemoryPanel({ ctx }: { ctx: Ctx }) {
  const [mem, setMem] = useState<Memory[]>([]);
  const done = ctx.jobs.filter((j) => j.state === "done").length;
  useEffect(() => {
    api.memory().then(setMem).catch(() => setMem([]));
  }, [done]);
  if (!mem.length) return <p className="text-sm text-neutral-400">まだ覚えていることは無い。スタジオで描くと、通った描く言葉と落ちた理由が残る</p>;
  return (
    <ul className="space-y-2 text-xs">
      {mem.map((m, k) => (
        <li key={k} className="rounded border border-line p-2">
          <p>
            <span className={m.ok ? "text-accent" : "text-signal"}>{m.ok ? "通った" : "落ちた"}</span> {m.text || "（描く言葉だけで頼んだ）"}
            <span className="ml-2 text-neutral-500">seed {m.seed}</span>
          </p>
          <p className="break-words font-mono text-neutral-400">{m.prompt}</p>
          {m.reason && <p className="text-signal">{m.reason}</p>}
        </li>
      ))}
    </ul>
  );
}

// 待機中に拾った提案。描くかは利用者が決める（承認するまで描かない）
function ProposalsPanel({ ctx }: { ctx: Ctx }) {
  const [p, setP] = useState<{ idle: boolean; items: Proposal[] }>({ idle: true, items: [] });
  const done = ctx.jobs.filter((j) => j.state === "done" || j.state === "failed").length;
  const load = () => api.proposals().then(setP).catch(() => setP({ idle: true, items: [] }));
  useEffect(() => {
    load();
  }, [done]);
  if (!p.idle) return <p className="text-sm text-neutral-400">描いている間は考えない（CPU を描くのに使う）</p>;
  if (!p.items.length) return <p className="text-sm text-neutral-400">いま提案は無い（拾える手がかりが無い）</p>;
  return (
    <ul className="space-y-2 text-sm">
      {p.items.map((x) => (
        <li key={x.id} className="rounded border border-line p-2">
          <p className="font-bold">{x.title}</p>
          <p className="text-xs text-neutral-400">{x.who}: {x.why}</p>
          <div className="mt-1 flex gap-2">
            <button type="button" className="rounded bg-accent px-3 py-0.5 text-xs font-bold text-ink"
              onClick={() => api.doProposal(x.id).then(() => { ctx.refreshJobs(); load(); }).catch((e: Error) => ctx.setError(e.message))}>
              描く
            </button>
            <button type="button" className="rounded border border-line px-3 py-0.5 text-xs"
              onClick={() => api.dismissProposal(x.id).then(load).catch((e: Error) => ctx.setError(e.message))}>
              退ける
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function QueuePanel({ ctx }: { ctx: Ctx }) {
  if (!ctx.jobs.length) return <p className="text-sm text-neutral-400">まだ無い</p>;
  return <ul className="space-y-3">{ctx.jobs.map((j) => <JobCard key={j.id} job={j} now={ctx.now} labels={ctx.labels} />)}</ul>;
}

// 置ける板。名前はサーバーの PANEL_KINDS（app/server/studio/layout.py）とそろえる。test_layout.py が食い違いを見る
export const PANELS: Record<string, { title: string; render: (ctx: Ctx) => ReactNode }> = {
  prompt: { title: "頼みごと", render: (ctx) => <PromptPanel ctx={ctx} /> },
  canvas: { title: "大きく見る", render: (ctx) => <CanvasPanel ctx={ctx} /> },
  gallery: { title: "描いた絵", render: (ctx) => <GalleryPanel ctx={ctx} /> },
  queue: { title: "仕事", render: (ctx) => <QueuePanel ctx={ctx} /> },
  roster: { title: "役割", render: (ctx) => <RosterPanel ctx={ctx} /> },
  log: { title: "出来事", render: (ctx) => <LogPanel ctx={ctx} /> },
  memory: { title: "覚えていること", render: (ctx) => <MemoryPanel ctx={ctx} /> },
  proposals: { title: "提案", render: (ctx) => <ProposalsPanel ctx={ctx} /> },
  demi: { title: "亜人の設定資料", render: (ctx) => <DemiPanel onSubmitted={ctx.refreshJobs} onError={ctx.setError} /> },
};

// 役割の一覧は一度だけ取る
export function useRoles(): Role[] {
  const [roles, setRoles] = useState<Role[]>([]);
  useEffect(() => {
    api.roles().then(setRoles).catch(() => setRoles([]));
  }, []);
  return roles;
}
