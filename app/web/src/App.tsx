import { useCallback, useEffect, useState } from "react";
import { api, type Case, type Job, type LlmStatus, type PartChoices } from "./api";
import CaseForm from "./CaseForm";
import FreePanel, { readerJa } from "./FreePanel";
import JobCard from "./JobCard";

// 描いている間だけ短い間隔で聞く。描き終わったら聞かない（1回 約3分かかるので、それより細かく見ても変わらない）
const POLL_MS = 5000;

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

export default function App() {
  const [cases, setCases] = useState<Record<string, Case>>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [tries, setTries] = useState(3);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  // 開いている種の設定の欄。new は新しく足す、それ以外は直す種の名前
  const [editing, setEditing] = useState<string | null>(null);
  const [labels, setLabels] = useState<PartChoices | null>(null);
  // 言葉で頼んで組んだ設定。種の欄に下書きとして渡す（保存は欄で見てから）
  const [draft, setDraft] = useState<{ name: string; case: Case } | null>(null);
  const [wish, setWish] = useState("");
  const [wishNotes, setWishNotes] = useState<string[]>([]);
  const [llm, setLlm] = useState<LlmStatus | null>(null);

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
    api.parts().then(setLabels).catch(() => setLabels(null));   // 向きと部品の日本語名。無くても英語名で出る
    api.llm().then(setLlm).catch(() => setLlm(null));
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

  const describe = () => {
    setError("");
    api
      .describe(wish)
      .then((r) => {
        // どれで読んだかを出す（手元の模型 → Claude（鍵があるとき）→ 辞書 の順に試す）
        const notes = [readerJa(r.reader), ...r.notes];
        if (r.unused.length) notes.unshift(`使わなかった言葉: ${r.unused.join("、")}`);
        setWishNotes(notes);
        if (r.case && r.name) {
          setDraft({ name: cases[r.name] ? `${r.name}-2` : r.name, case: r.case });
          setEditing("draft");
        }
      })
      .catch((e: Error) => setError(e.message));
  };

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
        <h2 className="mb-2 font-bold">自由に描く</h2>
        <FreePanel status={llm} onStatus={setLlm} onSubmitted={refreshJobs} onError={setError} />
      </section>

      <section className="mt-8">
        <h2 className="mb-2 font-bold">亜人の設定資料を言葉で頼む</h2>
        <form
          className="mb-6 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (wish.trim()) describe();
          }}
        >
          <input
            className="min-w-0 flex-1 rounded border border-line bg-panel px-3 py-1.5"
            value={wish}
            onChange={(e) => setWish(e.target.value)}
            placeholder="白い狐の巫女、銀髪で青い目の狼娘 など"
            aria-label="頼みごと"
          />
          <button type="submit" disabled={!wish.trim()} className="rounded border border-accent px-4 py-1.5 disabled:opacity-40">
            設定を組む
          </button>
          {wishNotes.length > 0 && (
            <ul className="w-full list-inside list-disc text-sm text-neutral-300">
              {wishNotes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </form>

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
              key={editing === "draft" ? `draft-${draft?.name}` : editing}
              name={editing === "new" ? "" : editing === "draft" ? (draft?.name ?? "") : editing}
              initial={
                editing === "new" ? { tags: "", hair: "", anatomy: [] } : editing === "draft" ? (draft?.case ?? {}) : (cases[editing] ?? {})
              }
              isNew={editing === "new" || editing === "draft"}
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
          <ul className="space-y-3">{jobs.map((j) => <JobCard key={j.id} job={j} now={now} labels={labels} />)}</ul>
        )}
      </section>
    </main>
  );
}
