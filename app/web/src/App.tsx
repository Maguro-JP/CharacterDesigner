import { useCallback, useEffect, useState } from "react";
import { api, type Case, type Job } from "./api";
import CaseForm from "./CaseForm";

const STATE_JA: Record<Job["state"], string> = {
  queued: "待ち",
  underlay: "下絵",
  drawing: "描画中",
  done: "完了",
  failed: "失敗",
};

// 描いている間だけ短い間隔で聞く。描き終わったら聞かない（1回 約3分かかるので、それより細かく見ても変わらない）
const POLL_MS = 5000;

function elapsed(job: Job, now: number): string {
  if (!job.started) return "-";
  const sec = Math.round(((job.finished ?? now / 1000) - job.started));
  return `${Math.floor(sec / 60)}分${sec % 60}秒`;
}

function CaseList({ cases, selected, onSelect }: { cases: Record<string, Case>; selected: string; onSelect: (name: string) => void }) {
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {Object.entries(cases).map(([name, c]) => (
        <li key={name}>
          <button
            type="button"
            onClick={() => onSelect(name)}
            className={`w-full rounded border px-3 py-2 text-left ${selected === name ? "border-accent bg-accent/15" : "border-line bg-panel hover:border-accent/60"}`}
          >
            <span className="block font-bold">{c.ja ?? name}</span>
            <span className="block text-xs text-neutral-400">{name}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function JobCard({ job, now }: { job: Job; now: number }) {
  const last = job.results.at(-1);
  const sheet = job.files.includes("sheet.png");
  return (
    <li className="rounded border border-line bg-panel p-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-bold">{job.case_name}</span>
        <span className={job.state === "failed" ? "text-signal" : job.state === "done" ? "text-accent" : "text-neutral-300"}>
          {STATE_JA[job.state]}
        </span>
        {job.try_index !== null && <span className="text-sm text-neutral-400">{job.try_index + 1} / {job.tries} 回目</span>}
        <span className="text-sm text-neutral-400">{elapsed(job, now)}</span>
        {job.state === "done" && <span className={job.passed ? "text-accent" : "text-signal"}>{job.passed ? "検品 通過" : "検品 不通過"}</span>}
      </div>
      {job.error && <p className="mt-1 text-sm text-signal">{job.error}</p>}
      {last && (
        <p className="mt-1 text-sm text-neutral-300">
          {last.try + 1} 回目の検品: {last.result.map((r) => `${r.view} ${r.part}${r.ok ? "○" : "×"}`).join("  ")}
        </p>
      )}
      {sheet && <img className="mt-2 w-full rounded bg-white" src={api.fileUrl(job.id, "sheet.png")} alt={`${job.case_name} の設定資料`} />}
    </li>
  );
}

export default function App() {
  const [cases, setCases] = useState<Record<string, Case>>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [tries, setTries] = useState(3);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  // 開いている種の設定の欄。new は新しく足す、それ以外は直す種の名前
  const [editing, setEditing] = useState<string | null>(null);

  const refreshJobs = useCallback(() => {
    api.jobs().then(setJobs).catch((e: Error) => setError(e.message));
  }, []);

  const loadCases = useCallback((select?: string) => {
    api
      .cases()
      .then((c) => {
        setCases(c);
        setSelected((s) => select || s || Object.keys(c)[0] || "");
      })
      .catch((e: Error) => setError(`サーバーに繋がらない: ${e.message}`));
  }, []);

  useEffect(() => {
    loadCases();
    refreshJobs();
  }, [loadCases, refreshJobs]);

  const busy = jobs.some((j) => j.state !== "done" && j.state !== "failed");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => {
      refreshJobs();
      setNow(Date.now());
    }, POLL_MS);
    return () => clearInterval(t);
  }, [busy, refreshJobs]);

  const submit = () => {
    setError("");
    api
      .submit(selected, tries)
      .then(refreshJobs)
      .catch((e: Error) => setError(e.message));
  };

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <h1 className="text-2xl font-bold tracking-wide">
        Character<span className="text-accent">Designer</span>
      </h1>
      {error && <p className="mt-3 rounded border border-signal p-2 text-signal">{error}</p>}

      <section className="mt-6">
        <h2 className="mb-2 font-bold">種を選ぶ</h2>
        <CaseList cases={cases} selected={selected} onSelect={setSelected} />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="text-sm">
            試す回数
            <select className="ml-2 rounded border border-line bg-panel px-2 py-1" value={tries} onChange={(e) => setTries(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <button type="button" disabled={!selected} onClick={submit} className="rounded bg-accent px-4 py-1.5 font-bold text-ink disabled:opacity-40">
            描く
          </button>
          <button type="button" disabled={!selected} onClick={() => setEditing(selected)} className="rounded border border-line px-3 py-1.5 disabled:opacity-40">
            直す
          </button>
          <button type="button" onClick={() => setEditing("new")} className="rounded border border-line px-3 py-1.5">
            新しく足す
          </button>
          <span className="text-xs text-neutral-400">CPU では1回 約3分。最初の1件はモデルの読み込みに 約10分</span>
        </div>
        {editing && (
          <div className="mt-4">
            <CaseForm
              key={editing}
              name={editing === "new" ? "" : editing}
              initial={editing === "new" ? { tags: "", hair: "", anatomy: [] } : (cases[editing] ?? {})}
              isNew={editing === "new"}
              onSaved={(name) => {
                setEditing(null);
                loadCases(name);
              }}
              onCancel={() => setEditing(null)}
            />
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="mb-2 font-bold">仕事</h2>
        {jobs.length === 0 ? <p className="text-sm text-neutral-400">まだ無い</p> : (
          <ul className="space-y-3">{jobs.map((j) => <JobCard key={j.id} job={j} now={now} />)}</ul>
        )}
      </section>
    </main>
  );
}
