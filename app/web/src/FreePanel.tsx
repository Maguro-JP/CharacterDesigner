import { useEffect, useState } from "react";
import { api, type FreeDescribe, type FreeJobIn, type LlmStatus, type Reader } from "./api";

export const READER_JA: Record<string, string> = {
  local: "手元の模型で読んだ",
  claude: "Claude で読んだ",
  words: "辞書で読んだ",
  tags: "英語のタグとしてそのまま使った",
  check: "描かない言葉の検査で止めた",
};

export function readerJa(r: Reader): string {
  return r ? (READER_JA[r] ?? r) : "読めなかった";
}

// 手元の言葉の模型の状態と入れ替え。窓口（同梱・Ollama・LM Studio など）と模型を選んで保存する。
// 保存はサーバーがつながることを確かめてから行う。空で保存すると既定（環境変数か同梱の窓口）に戻る
export function LlmSettings({ status, onChange }: { status: LlmStatus | null; onChange: (s: LlmStatus) => void }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!open || !status) return;
    setUrl(status.saved?.url ?? "");
    setModel(status.local.model ?? "");
    setModels(status.local.models ?? []);
  }, [open, status]);

  if (!status) return null;
  const { local } = status;

  const probe = () => {
    setMsg("");
    api
      .llmProbe(url)
      .then((r) => {
        setModels(r.models ?? []);
        setModel((m) => (r.models?.includes(m) ? m : (r.models?.[0] ?? "")));
        setMsg(r.ok ? `つながった。模型 ${r.models?.length ?? 0} 個` : `つながらない: ${r.error ?? ""}`);
      })
      .catch((e: Error) => setMsg(e.message));
  };

  const save = (u: string, m: string) => {
    setMsg("");
    api
      .llmSave(u, m)
      .then((s) => {
        onChange(s);
        setMsg("入れ替えた");
      })
      .catch((e: Error) => setMsg(e.message));
  };

  return (
    <div className="text-xs text-neutral-400">
      <p>
        言葉の模型:{" "}
        {local.ok ? (
          <span className="text-accent">{local.model}（{local.url}）</span>
        ) : (
          <span className="text-signal">つながらない（初回の設定で取っていなければ辞書で読みます。起動し直すか、ここで窓口を選ぶ）</span>
        )}
        {status.claude && "・Claude の鍵あり"}
        <button type="button" className="ml-2 underline" onClick={() => setOpen((o) => !o)}>
          {open ? "閉じる" : "入れ替える"}
        </button>
      </p>
      {open && (
        <div className="mt-2 space-y-2 rounded border border-line bg-panel p-2 text-sm text-neutral-200">
          <label className="block">
            窓口の URL（空なら既定 {status.default_url}。Ollama は http://127.0.0.1:11434/v1、LM Studio は http://127.0.0.1:1234/v1）
            <div className="mt-1 flex flex-wrap gap-2">
              <input
                className="min-w-0 flex-1 rounded border border-line bg-ink px-2 py-1 font-mono text-xs"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={status.default_url}
                aria-label="言葉の模型の窓口"
              />
              <button type="button" className="rounded border border-line px-3 py-1" onClick={probe}>
                模型を調べる
              </button>
            </div>
          </label>
          <label className="block">
            模型
            <select className="ml-2 rounded border border-line bg-ink px-2 py-1" value={model} onChange={(e) => setModel(e.target.value)} aria-label="言葉の模型">
              {models.length === 0 && <option value="">（先に模型を調べる）</option>}
              {models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!model} className="rounded bg-accent px-3 py-1 font-bold text-ink disabled:opacity-40" onClick={() => save(url, model)}>
              この模型にする
            </button>
            <button type="button" className="rounded border border-line px-3 py-1" onClick={() => save("", "")}>
              既定に戻す
            </button>
          </div>
          <p className="text-xs text-neutral-400">同梱の窓口に模型を足すには `CD_LLM_SIZE=large sh tools/llm/setup.sh`（または CD_LLM_GGUF_URL）を流して起動し直す</p>
          {msg && <p className="text-xs">{msg}</p>}
        </div>
      )}
    </div>
  );
}

type Props = { status: LlmStatus | null; onStatus: (s: LlmStatus) => void; onSubmitted: () => void; onError: (msg: string) => void };

export default function FreePanel({ status, onStatus, onSubmitted, onError }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [got, setGot] = useState<FreeDescribe | null>(null);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [size, setSize] = useState<FreeJobIn["size"]>("portrait");
  const [count, setCount] = useState(1);
  const [seed, setSeed] = useState(0);

  // 読み直したら、直しかけの描く言葉は読んだ結果で置き換える
  useEffect(() => {
    if (got?.allowed) {
      setPrompt(got.prompt);
      setNegative(got.negative);
    }
  }, [got]);

  const describe = () => {
    setBusy(true);
    onError("");
    api
      .freeDescribe(text)
      .then(setGot)
      .catch((e: Error) => onError(e.message))
      .finally(() => setBusy(false));
  };

  const submit = () => {
    onError("");
    api
      .freeSubmit({ prompt, negative, ja: text, seed, count, size })
      .then(() => {
        onSubmitted();
        setSeed((s) => s + count);   // 次に描くときは別の絵になるよう進めておく（同じ絵を描き直したければ戻せる）
      })
      .catch((e: Error) => onError(e.message));
  };

  return (
    <div className="space-y-3">
      <LlmSettings status={status} onChange={onStatus} />
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) describe();
        }}
      >
        <input
          className="min-w-0 flex-1 rounded border border-line bg-panel px-3 py-1.5"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="赤いマフラーの騎士の少年、雪の城の前 など"
          aria-label="自由に描く頼みごと"
          maxLength={200}
        />
        <button type="submit" disabled={!text.trim() || busy} className="rounded border border-accent px-4 py-1.5 disabled:opacity-40">
          {busy ? "読んでいる…" : "描く言葉に直す"}
        </button>
      </form>

      {got && (
        <div className="rounded border border-line bg-panel p-3 text-sm">
          <p className="text-neutral-400">{readerJa(got.reader)}{got.summary && `: ${got.summary}`}</p>
          {got.notes.map((n) => <p key={n} className="text-xs text-neutral-400">{n}</p>)}
          {!got.allowed && <p className="mt-1 text-signal">{got.reason}</p>}
          {!!got.advice?.length && (
            <div role="note" aria-label="宗教・文化の知らせ" className="mt-2 rounded border border-signal p-2">
              <p className="text-xs font-bold text-signal">描く前に確かめる（宗教・文化）</p>
              {got.advice.map((a) => <p key={a} className="mt-1 text-xs">{a}</p>)}
            </div>
          )}
        </div>
      )}

      {got?.allowed && (
        <div className="space-y-2 rounded border border-line bg-panel p-3">
          <label className="block text-sm">
            描く言葉（英語のタグ。直してから描ける）
            <textarea className="mt-1 h-24 w-full rounded border border-line bg-ink px-2 py-1 font-mono text-xs" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>
          <label className="block text-sm">
            描かないもの（打ち消し）
            <textarea className="mt-1 h-12 w-full rounded border border-line bg-ink px-2 py-1 font-mono text-xs" value={negative} onChange={(e) => setNegative(e.target.value)} />
          </label>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label>
              形
              <select className="ml-2 rounded border border-line bg-ink px-2 py-1" value={size} onChange={(e) => setSize(e.target.value as FreeJobIn["size"])}>
                <option value="portrait">縦長</option>
                <option value="landscape">横長</option>
                <option value="square">正方形</option>
              </select>
            </label>
            <label>
              枚数
              <select className="ml-2 rounded border border-line bg-ink px-2 py-1" value={count} onChange={(e) => setCount(Number(e.target.value))}>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label>
              seed
              <input type="number" min={0} className="ml-2 w-24 rounded border border-line bg-ink px-2 py-1" value={seed} onChange={(e) => setSeed(Math.max(0, Number(e.target.value) || 0))} />
            </label>
            <button type="button" disabled={!prompt.trim()} onClick={submit} className="rounded bg-accent px-4 py-1.5 font-bold text-ink disabled:opacity-40">
              描く
            </button>
            <span className="text-xs text-neutral-400">CPU では1枚 約2〜3分。最初の1件はモデルの読み込みに 約10分</span>
          </div>
        </div>
      )}
    </div>
  );
}
