import { useEffect, useState } from "react";
import { api, type SetupStatus } from "./api";

// 初回の設定。取る物を選ばせ、取っている間は進みを出す。終わったら onDone で作業の画面へ移る
export default function Setup({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const [s, setS] = useState(status);
  const [image, setImage] = useState(true);
  const [llm, setLlm] = useState("default");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!s.running) return;
    const t = setInterval(() => api.setup().then(setS).catch((e: Error) => setError(e.message)), 2000);
    return () => clearInterval(t);
  }, [s.running]);

  const start = () => {
    setError("");
    api.startSetup(image, llm).then(setS).catch((e: Error) => setError(e.message));
  };

  const choosing = !s.running && !s.done;
  return (
    <main className="mx-auto max-w-xl px-4 py-10">
      <h1 className="mb-1 text-xl font-bold tracking-wide">
        Character<span className="text-accent">Designer</span> の初回の設定
      </h1>
      <p className="mb-6 text-sm text-neutral-400">描くのに使う模型を、このパソコンに取ります。取るのは最初の 1 回だけです。空き {s.free_gb}GB</p>

      {choosing && (
        <>
          <fieldset className="mb-5 rounded border border-neutral-700 p-4">
            <legend className="px-1 text-sm font-bold">絵の模型（{s.sizes.image_model}）</legend>
            <p className="mb-2 text-xs text-neutral-400">絵を描く本体です。取らないと絵は描けません。</p>
            <label className="mr-4 text-sm"><input type="radio" checked={image} onChange={() => setImage(true)} /> 取る</label>
            <label className="text-sm"><input type="radio" checked={!image} onChange={() => setImage(false)} /> 取らない</label>
          </fieldset>
          <fieldset className="mb-6 rounded border border-neutral-700 p-4">
            <legend className="px-1 text-sm font-bold">言葉の模型</legend>
            <p className="mb-2 text-xs text-neutral-400">日本語の頼みを、絵を描く言葉に直します。取らなければ辞書で読みます。</p>
            {([["default", `取る（標準、${s.sizes.default}）`], ["small", `取る（小さい版、${s.sizes.small}。メモリ 8GB 以下のパソコン向け）`], ["no", "取らない"]] as [string, string][]).map(([k, label]) => (
              <label key={k} className="block text-sm"><input type="radio" checked={llm === k} onChange={() => setLlm(k)} /> {label}</label>
            ))}
          </fieldset>
          <button type="button" className="rounded bg-accent px-4 py-2 font-bold text-white" onClick={start}>この内容で始める</button>
        </>
      )}

      {(s.running || s.done) && (
        <div className="rounded border border-neutral-700 p-4">
          <p className="mb-2 text-sm">{s.step || "準備しています…"}</p>
          <div className="h-3 w-full rounded bg-neutral-800">
            <div className="h-3 rounded bg-accent" style={{ width: `${s.percent ?? 0}%` }} />
          </div>
          <p className="mt-1 text-xs text-neutral-400">{s.percent != null ? `${s.percent}%` : ""}</p>
          {s.done && !s.error && <button type="button" className="mt-4 rounded bg-accent px-4 py-2 font-bold text-white" onClick={onDone}>描き始める</button>}
        </div>
      )}

      {(s.error || error) && (
        <div className="mt-4 rounded border border-signal p-3 text-sm text-signal">
          <p>{s.error || error}</p>
          {!s.running && <button type="button" className="mt-2 underline" onClick={() => setS({ ...s, done: false, error: "" })}>選び直してもう一度</button>}
        </div>
      )}
    </main>
  );
}
