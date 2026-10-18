import { useEffect, useState, type ReactNode } from "react";
import { api, type Bible, type Job, type LlmStatus, type Lora, type Memory, type PartChoices, type Proposal, type Role, type StudioIn } from "./api";
import DemiPanel from "./DemiPanel";
import { LlmSettings, readerJa } from "./FreePanel";
import JobCard from "./JobCard";
import PaintPanel from "./PaintPanel";
import FiltersPanel from "./FiltersPanel";
import RefsPanel from "./RefsPanel";

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
      // 人の順番で描き直した仕上げも並べる（段ごとの絵は hd-<元>-<段>.png。並べるのは仕上げだけ）
      j.files.filter((f) => /^hd-try-\d+-5-final\.png$/.test(f)).forEach((f) =>
        out.push({ jobId: j.id, file: f, label: `${j.case_name}（人の順番）`, passed: true, prompt: j.outcome?.prompt ?? "", job: j }));
    } else if (j.kind === "free") {
      j.results.forEach((r) => r.file && out.push({ jobId: j.id, file: r.file, label: j.case_name, passed: true, prompt: j.free?.prompt ?? "", job: j }));
    } else if (j.files.includes("sheet.png")) {
      out.push({ jobId: j.id, file: "sheet.png", label: j.case_name, passed: true, prompt: "", job: j });
    }
  }
  // 仕事は新しい順に来るので、そのまま新しい絵が先頭（「大きく見る」も既定で一番新しい絵を出す）
  return out.filter((i) => i.job.files.includes(i.file));
}

// 線の作風の日本語名（casts/brushes.json の styles）
const LINE_JA = {default: "標準", chibi: "デフォルメ（太い線）", cute: "かわいい（丸い線）", cool: "格好いい（鋭い線）", manga: "漫画", sketch: "鉛筆"};

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
  const [lora, setLora] = useState("");
  const [paint, setPaint] = useState("");
  const [format, setFormat] = useState("");
  const [styles, setStyles] = useState<Record<"paint" | "format", { id: string; ja: string; refs: string }[]>>({ paint: [], format: [] });
  useEffect(() => {
    api.styles().then(setStyles).catch(() => setStyles({ paint: [], format: [] }));
  }, []);
  const [pose, setPose] = useState("");
  const [method, setMethod] = useState<StudioIn["method"]>("oneshot");
  const [allowImpossible, setAllowImpossible] = useState(false);
  const [brush, setBrush] = useState("");
  const [lineStyle, setLineStyle] = useState("default");
  const [paintMethod, setPaintMethod] = useState<"cel" | "grisaille">("cel");
  // 設定資料集（保存したキャラクターと世界観）から描く。選ぶと、見た目・服・持ち物・場所の言葉はサーバーが組み立てる
  const [bible, setBible] = useState<Bible>({ characters: [], worlds: [] });
  useEffect(() => {
    api.bible().then(setBible).catch(() => undefined);
  }, []);
  const [character, setCharacter] = useState("");
  const [world, setWorld] = useState("");
  const [location, setLocation] = useState("");
  const [scene, setScene] = useState("");
  const [act, setAct] = useState("");
  const [outfit, setOutfit] = useState("");
  const [brushList, setBrushList] = useState<{ brushes: { id: string; ja: string }[]; styles: string[] }>({ brushes: [], styles: ["default"] });
  useEffect(() => {
    api.brushes().then(setBrushList).catch(() => undefined);
  }, []);
  const [shelf, setShelf] = useState<{ lora: Lora[]; pose: { name: string; title: string; license: string; usable: boolean; why: string }[]; dir: string }>({ lora: [], pose: [], dir: "" });
  useEffect(() => {
    api.assets().then(setShelf).catch(() => setShelf({ lora: [], pose: [], dir: "" }));
  }, []);

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
      .studioSubmit({ text, prompt, negative, seed, size, tries, direct, lora, paint, format, pose, method, allow_impossible: allowImpossible, brush, line_style: lineStyle, paint_method: paintMethod, character, world, location, scene, act, outfit })
      .then(() => {
        ctx.refreshJobs();
        setSeed((s) => s + tries);   // 次は別の絵になるよう進める（同じ絵を描き直したければ戻せる）
      })
      .catch((e: Error) => ctx.setError(e.message));
  };

  const turnaround = () => {
    ctx.setError("");
    api
      .bibleTurnaround(character, 1, seed)
      .then(() => ctx.refreshJobs())
      .catch((e: Error) => ctx.setError(e.message));
  };

  const sel = "ml-1 rounded border border-line bg-ink px-2 py-1";
  const places = bible.worlds.find((w) => w.id === world)?.locations ?? [];
  return (
    <div className="space-y-2 text-sm">
      {bible.characters.length > 0 && (
        <fieldset className="space-y-1 rounded border border-line p-2">
          <legend className="px-1 text-xs text-neutral-400">設定資料集から描く（同じキャラクターとして描く）</legend>
          <div className="flex flex-wrap gap-2">
            <label>キャラクター
              <select className={sel} value={character} onChange={(e) => setCharacter(e.target.value)} aria-label="キャラクター">
                <option value="">使わない</option>
                {bible.characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label>世界観
              <select className={sel} value={world} onChange={(e) => { setWorld(e.target.value); setLocation(""); }} aria-label="世界観">
                <option value="">白い背景</option>
                {bible.worlds.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </label>
            {places.length > 0 && (
              <label>場所
                <select className={sel} value={location} onChange={(e) => setLocation(e.target.value)} aria-label="場所">
                  <option value="">世界観だけ</option>
                  {places.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            )}
          </div>
          {character && (
            <div className="grid gap-1">
              <input className="rounded border border-line bg-ink px-2 py-1" value={scene} onChange={(e) => setScene(e.target.value)} placeholder="場面（例: walking in the snow）" aria-label="場面" />
              <input className="rounded border border-line bg-ink px-2 py-1" value={act} onChange={(e) => setAct(e.target.value)} placeholder="ポーズ・しぐさ（例: looking back）" aria-label="ポーズ" />
              <input className="rounded border border-line bg-ink px-2 py-1" value={outfit} onChange={(e) => setOutfit(e.target.value)} placeholder="服を変えるときだけ（空ならいつもの服）" aria-label="服" />
              {/* 三面図は人形の下絵から描く（言葉だけでは横が斜め前、後ろが振り返った）。CPU で1枚 数分 × 3方向 */}
              <button type="button" onClick={turnaround} className="justify-self-start rounded border border-line px-3 py-1">
                三面図を描く（正面・横・後ろ、時間がかかる）
              </button>
            </div>
          )}
        </fieldset>
      )}
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
        <button type="button" disabled={!character && !text.trim() && !prompt.trim()} onClick={submit} className="rounded bg-accent px-4 py-1 font-bold text-ink disabled:opacity-40">
          スタジオに頼む
        </button>
      </div>
      {note && <p className="text-xs text-neutral-400">{note}</p>}
      <CulturalAdvice text={`${text}, ${prompt}`} />
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
        <label>
          手順
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={method} onChange={(e) => setMethod(e.target.value as StudioIn["method"])} aria-label="生成手順">
            <option value="oneshot">一発で描く（速い）</option>
            <option value="handdraw">描いてから人の順番で仕上げ直す</option>
            <option value="rough">ラフから人の順番で描く（こだわる）</option>
          </select>
        </label>
        {method !== "oneshot" && (
          <>
            <label>
              塗り方
              <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={paintMethod} onChange={(e) => setPaintMethod(e.target.value as "cel" | "grisaille")} aria-label="塗り方">
                <option value="cel">セル塗り（影を面で置く）</option>
                <option value="grisaille">グリザイユ（灰色の明暗に色を重ねる）</option>
              </select>
            </label>
            <label>
              線の作風
              <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={lineStyle} onChange={(e) => setLineStyle(e.target.value)} aria-label="線の作風">
                {brushList.styles.map((x) => <option key={x} value={x}>{(LINE_JA as Record<string, string>)[x] ?? x}</option>)}
              </select>
            </label>
            <label>
              ブラシ
              <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={brush} onChange={(e) => setBrush(e.target.value)} aria-label="線のブラシ">
                <option value="">作風のまま</option>
                {brushList.brushes.map((x) => <option key={x.id} value={x.id}>{x.ja}</option>)}
              </select>
            </label>
          </>
        )}
        <label className="flex items-center gap-1" title="余分な手足・浮いた物など、あり得ない形を描いてよいか。特別な注文のときだけ">
          <input type="checkbox" checked={allowImpossible} onChange={(e) => setAllowImpossible(e.target.checked)} />
          あり得ない形を許す
        </label>
        <label>
          塗り
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={paint} onChange={(e) => setPaint(e.target.value)} aria-label="塗り">
            <option value="">おまかせ</option>
            {styles.paint.map((x) => <option key={x.id} value={x.id} title={x.refs}>{x.ja}</option>)}
          </select>
        </label>
        <label>
          見せ方
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={format} onChange={(e) => setFormat(e.target.value)} aria-label="見せ方">
            <option value="">おまかせ</option>
            {styles.format.map((x) => <option key={x.id} value={x.id} title={x.refs}>{x.ja}</option>)}
          </select>
        </label>
        <label>
          素材
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={lora} onChange={(e) => setLora(e.target.value)} aria-label="素材（LoRA）">
            <option value="">使わない</option>
            {shelf.lora.map((l) => (
              <option key={l.name} value={l.name} disabled={!l.usable} title={l.usable ? `${l.license}・${l.source}` : l.why}>
                {l.title}{l.usable ? "" : "（出典なし）"}
              </option>
            ))}
          </select>
        </label>
        <label>
          姿勢
          <select className="ml-1 rounded border border-line bg-ink px-2 py-1" value={pose} onChange={(e) => setPose(e.target.value)} aria-label="姿勢の下絵">
            <option value="">おまかせ</option>
            {shelf.pose.map((x) => (
              <option key={x.name} value={x.name} disabled={!x.usable} title={x.usable ? x.license : x.why}>{x.title}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={direct} onChange={(e) => setDirect(e.target.checked)} />
          演出に構図と光を任せる
        </label>
      </div>
      <p className="text-xs text-neutral-400">CPU では1枚 約2〜3分。最初の1件は描く模型の読み込みに 約10分</p>
      {shelf.lora.length === 0 && (
        <p className="text-xs text-neutral-500">素材（LoRA）を足すには `python3 tools/gen/assets.py add URL 名前 --license ライセンス`（置き場 {shelf.dir}）</p>
      )}
    </div>
  );
}

function CanvasPanel({ ctx }: { ctx: Ctx }) {
  const items = galleryItems(ctx.jobs);
  const cur = items.find((i) => ctx.selected && i.jobId === ctx.selected.jobId && i.file === ctx.selected.file) ?? items[0];
  const [notan, setNotan] = useState(false);
  const [liked, setLiked] = useState("");
  const [hd, setHd] = useState("");
  const [sceneOf, setSceneOf] = useState("");
  const [sceneName, setSceneName] = useState("");
  const [sceneSaved, setSceneSaved] = useState("");
  const [chars, setChars] = useState<Bible["characters"]>([]);
  useEffect(() => {
    api.bible().then((b) => setChars(b.characters)).catch(() => undefined);
  }, []);
  if (!cur) return <p className="text-sm text-neutral-400">まだ描いた絵が無い。頼みごとを書いて「スタジオに頼む」</p>;
  const notanFile = cur.file.replace(".png", "-notan.png");
  const hasNotan = cur.job.files.includes(notanFile);
  const critique = cur.passed ? (cur.job.outcome?.critique ?? []) : [];
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-2 text-sm">
        <span className="font-bold">{cur.label}</span>
        {cur.job.kind === "studio" && <span className={cur.passed ? "text-accent" : "text-signal"}>{cur.passed ? "検品 通過" : "検品 不通過"}</span>}
        {cur.job.kind === "studio" && (
          <button type="button" className="ml-auto rounded border border-accent px-2 py-0.5 text-xs" disabled={liked === cur.jobId + cur.file}
            onClick={() => api.like(cur.jobId, cur.file).then(() => setLiked(cur.jobId + cur.file)).catch((e: Error) => ctx.setError(e.message))}>
            {liked === cur.jobId + cur.file ? "覚えた" : "良い（この描き方を覚える）"}
          </button>
        )}
        {cur.job.kind === "studio" && chars.length > 0 && (
          <span className="flex items-center gap-1 text-xs">
            <select className="rounded border border-line bg-ink px-1 py-0.5" value={sceneOf} onChange={(e) => setSceneOf(e.target.value)} aria-label="場面として残すキャラクター">
              <option value="">場面として残す先</option>
              {chars.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input className="w-28 rounded border border-line bg-ink px-1 py-0.5" value={sceneName} onChange={(e) => setSceneName(e.target.value)} placeholder="名前（英小文字）" aria-label="場面の名前" />
            <button type="button" className="rounded border border-line px-2 py-0.5" disabled={!sceneOf || !/^[a-z0-9-]{1,40}$/.test(sceneName)}
              onClick={() => api.bibleScene(sceneOf, cur.jobId, cur.file, sceneName).then(() => setSceneSaved(cur.jobId + cur.file)).catch((e: Error) => ctx.setError(e.message))}>
              {sceneSaved === cur.jobId + cur.file ? "残した" : "場面として残す"}
            </button>
          </span>
        )}
        {/^try-\d+\.png$/.test(cur.file) && (
          <button type="button" className="rounded border border-line px-2 py-0.5 text-xs" disabled={hd === "busy"}
            onClick={() => {
              setHd("busy");
              api.handdraw(cur.jobId, cur.file).then(() => { setHd(""); ctx.refreshJobs(); }).catch((e: Error) => { setHd(""); ctx.setError(e.message); });
            }}>
            {hd === "busy" ? "人の順番で描いている…" : "人の順番で描き直す"}
          </button>
        )}
        {hasNotan && (
          <button type="button" className="underline" onClick={() => setNotan((n) => !n)}>
            {notan ? "絵に戻す" : "明暗の塊を見る"}
          </button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center rounded bg-black/30">
        <img className="max-h-full max-w-full object-contain" src={api.fileUrl(cur.jobId, notan && hasNotan ? notanFile : cur.file)} alt={`${cur.label} を大きく見る`} />
      </div>
      {cur.prompt && <p className="break-words font-mono text-xs text-neutral-400">{cur.prompt}</p>}
      {critique.map((c) => <p key={c} className="text-xs text-neutral-300">CRITIC: {c}</p>)}
      {!!cur.job.outcome?.findings?.length && (
        <details className="text-xs text-neutral-400">
          <summary>見つけた矛盾・あり得ないこと {cur.job.outcome.findings.length} 件</summary>
          <ul className="list-inside list-disc">{cur.job.outcome.findings.map((f) => <li key={f}>{f}</li>)}</ul>
        </details>
      )}
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
            <span className={m.liked ? "text-accent" : m.ok ? "text-neutral-300" : "text-signal"}>{m.liked ? "良い（手本にする）" : m.ok ? "通った" : "落ちた"}</span> {m.text || "（描く言葉だけで頼んだ）"}
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
  paint: { title: "描く", render: (ctx) => <PaintPanel ctx={ctx} /> },
  gallery: { title: "描いた絵", render: (ctx) => <GalleryPanel ctx={ctx} /> },
  queue: { title: "仕事", render: (ctx) => <QueuePanel ctx={ctx} /> },
  roster: { title: "役割", render: (ctx) => <RosterPanel ctx={ctx} /> },
  log: { title: "出来事", render: (ctx) => <LogPanel ctx={ctx} /> },
  memory: { title: "覚えていること", render: (ctx) => <MemoryPanel ctx={ctx} /> },
  proposals: { title: "提案", render: (ctx) => <ProposalsPanel ctx={ctx} /> },
  demi: { title: "亜人の設定資料", render: (ctx) => <DemiPanel onSubmitted={ctx.refreshJobs} onError={ctx.setError} /> },
  filters: { title: "フィルター", render: (ctx) => <FiltersPanel ctx={ctx} /> },
  refs: { title: "参考画像", render: (ctx) => <RefsPanel ctx={ctx} /> },
};

// 役割の一覧は一度だけ取る
export function useRoles(): Role[] {
  const [roles, setRoles] = useState<Role[]>([]);
  useEffect(() => {
    api.roles().then(setRoles).catch(() => setRoles([]));
  }, []);
  return roles;
}

/** 宗教・文化の上で見る人を傷つけやすい頼みごとに、描く前の知らせを出す。止めはしない（描くかは利用者が決める） */
export function CulturalAdvice({ text }: { text: string }) {
  const [advice, setAdvice] = useState<string[]>([]);
  useEffect(() => {
    if (!text.replace(/[,\s]/g, "")) { setAdvice([]); return; }
    // 打つたびに聞かないよう、手が止まってから聞く
    const t = setTimeout(() => api.cultural(text).then((r) => setAdvice(r.advice)).catch(() => setAdvice([])), 400);
    return () => clearTimeout(t);
  }, [text]);
  if (!advice.length) return null;
  return (
    <div role="note" aria-label="宗教・文化の知らせ" className="rounded border border-signal p-2">
      <p className="text-xs font-bold text-signal">描く前に確かめる（宗教・文化）</p>
      {advice.map((a) => <p key={a} className="mt-1 text-xs">{a}</p>)}
    </div>
  );
}
