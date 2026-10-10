import { useCallback, useEffect, useState } from "react";
import { api, type Case } from "./api";
import CaseForm from "./CaseForm";
import { readerJa } from "./FreePanel";

// 亜人の設定資料の欄（前からの機能）。言葉で頼んで種の設定を組む・種を選んで描く・種を直す
function CaseList({ cases, selected, onSelect }: { cases: Record<string, Case>; selected: string; onSelect: (name: string) => void }) {
  return (
    <ul className="grid grid-cols-2 gap-2">
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

export default function DemiPanel({ onSubmitted, onError }: { onSubmitted: () => void; onError: (msg: string) => void }) {
  const [cases, setCases] = useState<Record<string, Case>>({});
  const [selected, setSelected] = useState("");
  const [tries, setTries] = useState(3);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ name: string; case: Case } | null>(null);
  const [wish, setWish] = useState("");
  const [wishNotes, setWishNotes] = useState<string[]>([]);

  const loadCases = useCallback(
    (select?: string) => {
      api
        .cases()
        .then((c) => {
          setCases(c);
          setSelected((s) => select || s || Object.keys(c)[0] || "");
        })
        .catch((e: Error) => onError(`サーバーに繋がらない: ${e.message}`));
    },
    [onError],
  );
  useEffect(() => loadCases(), [loadCases]);

  const describe = () => {
    onError("");
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
      .catch((e: Error) => onError(e.message));
  };

  const submit = () => {
    onError("");
    api
      .submit(selected, tries)
      .then(onSubmitted)
      .catch((e: Error) => onError(e.message));
  };

  return (
    <div className="space-y-3 text-sm">
      <form
        className="flex flex-wrap gap-2"
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
        <button type="submit" disabled={!wish.trim()} className="rounded border border-accent px-3 py-1.5 disabled:opacity-40">
          設定を組む
        </button>
        {wishNotes.length > 0 && (
          <ul className="w-full list-inside list-disc text-neutral-300">
            {wishNotes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
      </form>
      <CaseList cases={cases} selected={selected} onSelect={setSelected} />
      <div className="flex flex-wrap items-center gap-2">
        <label>
          試す回数
          <select className="ml-2 rounded border border-line bg-panel px-2 py-1" value={tries} onChange={(e) => setTries(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="button" disabled={!selected} onClick={submit} className="rounded bg-accent px-3 py-1.5 font-bold text-ink disabled:opacity-40">
          描く
        </button>
        <button type="button" disabled={!selected} onClick={() => setEditing(selected)} className="rounded border border-line px-3 py-1.5 disabled:opacity-40">
          直す
        </button>
        <button type="button" onClick={() => setEditing("new")} className="rounded border border-line px-3 py-1.5">
          新しく足す
        </button>
      </div>
      {editing && (
        <CaseForm
          key={editing === "draft" ? `draft-${draft?.name}` : editing}
          name={editing === "new" ? "" : editing === "draft" ? (draft?.name ?? "") : editing}
          initial={editing === "new" ? { tags: "", hair: "", anatomy: [] } : editing === "draft" ? (draft?.case ?? {}) : (cases[editing] ?? {})}
          isNew={editing === "new" || editing === "draft"}
          onSaved={(name) => {
            setEditing(null);
            loadCases(name);
          }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}
