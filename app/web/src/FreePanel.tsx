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

// 手元の言葉の模型の状態。日本語を描く言葉に直せるかどうかが、ここで分かる
export function LlmBadge({ status }: { status: LlmStatus | null }) {
  if (!status) return null;
  const { local } = status;
  return (
    <p className="text-xs text-neutral-400">
      言葉の模型:{" "}
      {local.ok ? (
        <span className="text-accent">手元の模型（{local.model}）につながっている</span>
      ) : (
        <span className="text-signal">手元の模型につながらない（`sh tools/llm/setup.sh` で入れて `sh app/start.sh` で起こす）</span>
      )}
      {status.claude && "・Claude の鍵あり"}
    </p>
  );
}

type Props = { status: LlmStatus | null; onSubmitted: () => void; onError: (msg: string) => void };

export default function FreePanel({ status, onSubmitted, onError }: Props) {
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
      <LlmBadge status={status} />
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
