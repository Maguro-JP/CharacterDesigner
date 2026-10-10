import { useState } from "react";
import { api, type Job, type PartChoices } from "./api";

const STATE_JA: Record<Job["state"], string> = {
  queued: "待ち",
  underlay: "下絵",
  drawing: "描画中",
  done: "完了",
  failed: "失敗",
};

function elapsed(job: Job, now: number): string {
  if (!job.started) return "-";
  const sec = Math.round((job.finished ?? now / 1000) - job.started);
  return `${Math.floor(sec / 60)}分${sec % 60}秒`;
}

type Props = { job: Job; now: number; labels: Pick<PartChoices, "view_ja" | "part_ja"> | null };

// 自由に描いた仕事。描けた絵をそのまま並べる（設定資料の検品は無い）
function FreeJobCard({ job, now }: { job: Job; now: number }) {
  const images = job.results.map((r) => r.file).filter((f): f is string => !!f && job.files.includes(f));
  return (
    <li className="rounded border border-line bg-panel p-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-bold">{job.case_name}</span>
        <span className="text-xs text-neutral-400">自由に描く</span>
        <span className={job.state === "failed" ? "text-signal" : job.state === "done" ? "text-accent" : "text-neutral-300"}>
          {STATE_JA[job.state]}
        </span>
        {job.state === "drawing" && <span className="text-sm text-neutral-400">{images.length} / {job.tries} 枚</span>}
        <span className="text-sm text-neutral-400">{elapsed(job, now)}</span>
      </div>
      {job.free && <p className="mt-1 break-words font-mono text-xs text-neutral-400">{job.free.prompt}（seed {job.free.seed}）</p>}
      {job.error && <p className="mt-1 text-sm text-signal">{job.error}</p>}
      {images.length > 0 && (
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {images.map((f, k) => (
            <a key={f} href={api.fileUrl(job.id, f)} target="_blank" rel="noreferrer">
              <img className="w-full rounded bg-white" src={api.fileUrl(job.id, f)} alt={`${job.case_name} の ${k + 1} 枚目（seed ${(job.free?.seed ?? 0) + k}）`} />
            </a>
          ))}
        </div>
      )}
    </li>
  );
}

export default function JobCard({ job, now, labels }: Props) {
  const [open, setOpen] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [needOverwrite, setNeedOverwrite] = useState(false);
  const sheet = job.files.includes("sheet.png");
  if (job.kind === "free") return <FreeJobCard job={job} now={now} />;
  const view = (v: string) => labels?.view_ja[v] ?? v;
  const part = (p: string) => labels?.part_ja[p] ?? p;

  const save = (overwrite: boolean) => {
    setSaveMsg("");
    api
      .saveSample(job.id, overwrite)
      .then((r) => {
        setSaveMsg(`保存した: ${r.saved}`);
        setNeedOverwrite(false);
      })
      .catch((e: Error) => {
        // 既に見本がある（409）ときは、置き換えるかを選ばせる。黙って上書きしない
        setSaveMsg(e.message);
        setNeedOverwrite(e.message.includes("既にある"));
      });
  };

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
        {job.results.length > 0 && (
          <button type="button" className="ml-auto text-sm underline" onClick={() => setOpen((o) => !o)}>
            {open ? "回ごとの結果を閉じる" : `回ごとの結果（${job.results.length}）`}
          </button>
        )}
      </div>
      {job.error && <p className="mt-1 text-sm text-signal">{job.error}</p>}

      {open && (
        <ol className="mt-2 space-y-3">
          {job.results.map(({ try: k, result }) => {
            const lost = (result ?? []).filter((r) => !r.ok);
            return (
              <li key={k} className="rounded border border-line p-2">
                <p className="text-sm">
                  <span className="font-bold">{k + 1} 回目</span>{" "}
                  {lost.length === 0 ? (
                    <span className="text-accent">通過</span>
                  ) : (
                    <span className="text-signal">落ちた理由: {lost.map((r) => `${view(r.view)}の${part(r.part)}`).join("、")}</span>
                  )}
                </p>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {job.files.includes(`try-${k}.png`) && (
                    <img className="w-full rounded bg-white" src={api.fileUrl(job.id, `try-${k}.png`)} alt={`${k + 1} 回目に描いた絵`} />
                  )}
                  {job.files.includes(`try-${k}-inspect.png`) && (
                    <img className="w-full rounded bg-white" src={api.fileUrl(job.id, `try-${k}-inspect.png`)} alt={`${k + 1} 回目の検品の図（部品ごとの ○×）`} />
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {sheet && (
        <>
          <img className="mt-2 w-full rounded bg-white" src={api.fileUrl(job.id, "sheet.png")} alt={`${job.case_name} の設定資料`} />
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <button type="button" onClick={() => save(false)} className="rounded border border-accent px-3 py-1">
              見本に保存
            </button>
            {needOverwrite && (
              <button type="button" onClick={() => save(true)} className="rounded border border-signal px-3 py-1 text-signal">
                前の見本と置き換える
              </button>
            )}
            <span className="text-xs text-neutral-400">機械の検品は通過。人の耳が残っていないか、部品の付け根の位置は目で見てから保存する</span>
          </div>
          {saveMsg && <p className="mt-1 text-sm text-neutral-300">{saveMsg}</p>}
        </>
      )}
    </li>
  );
}
