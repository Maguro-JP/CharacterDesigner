import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ASSIST_DEFAULT, ASSIST_OFF, drawStroke, finishStroke, follow, loadAssist, PRESET, saveAssist, type Assist, type Pt } from "./paint";
import { galleryItems, type Ctx } from "./panels";

// 描く板。選んだ絵を下絵に敷き、その上の透明な層に描く。下絵には描き込まない（何度でもやり直せるように）
// 大きさは描いた絵と同じ 832x1216。画面の大きさに合わせて縮めて見せ、座標は元の大きさに直して描く
const W = 832;
const H = 1216;
const UNDO = 30;

type Tool = "pen" | "eraser" | "picker";
// レイヤー。線画と塗りを分けるため。下から順に重ねる
type Layer = { id: number; name: string; visible: boolean; opacity: number };
let nextLayer = 3;

export default function PaintPanel({ ctx }: { ctx: Ctx }) {
  const items = galleryItems(ctx.jobs);
  const cur = items.find((i) => ctx.selected && i.jobId === ctx.selected.jobId && i.file === ctx.selected.file) ?? items[0];
  const under = cur ? api.fileUrl(cur.jobId, cur.file) : "";

  const [layers, setLayers] = useState<Layer[]>([{ id: 1, name: "塗り", visible: true, opacity: 1 }, { id: 2, name: "線画", visible: true, opacity: 1 }]);
  const [activeId, setActiveId] = useState(2);
  const canvases = useRef(new Map<number, HTMLCanvasElement>());
  const active = useRef(2);
  active.current = activeId;
  const live = useRef<HTMLCanvasElement>(null);
  const underImg = useRef<HTMLImageElement>(null);
  const stroke = useRef<Pt[]>([]);
  const last = useRef<Pt | null>(null);
  // 戻すは、どのレイヤーの絵だったかも覚える
  const undo = useRef<{ id: number; data: ImageData }[]>([]);
  const redo = useRef<{ id: number; data: ImageData }[]>([]);

  const [tool, setTool] = useState<Tool>("pen");
  const [color, setColor] = useState("#000000");
  const [size, setSize] = useState(6);
  const [alpha, setAlpha] = useState(1);
  const [assist, setAssistState] = useState<Assist>(loadAssist);
  const setAssist = (p: Partial<Assist>) => setAssistState((a) => { const n = { ...a, ...p }; saveAssist(n); return n; });
  const [underAlpha, setUnderAlpha] = useState(0.5);
  const [recent, setRecent] = useState<string[]>([]);
  const [, bump] = useState(0);

  const ctxOf = (id: number) => canvases.current.get(id)?.getContext("2d", { willReadFrequently: true }) ?? null;
  const g = () => ctxOf(active.current);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      e.preventDefault();
      if (e.shiftKey) doRedo();
      else doUndo();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const snapshot = () => {
    const c = g();
    if (!c) return;
    undo.current.push({ id: active.current, data: c.getImageData(0, 0, W, H) });
    if (undo.current.length > UNDO) undo.current.shift();
    redo.current = [];
    bump((n) => n + 1);
  };
  const doUndo = () => {
    const prev = undo.current.pop();
    const c = prev && ctxOf(prev.id);
    if (!c || !prev) return;
    redo.current.push({ id: prev.id, data: c.getImageData(0, 0, W, H) });
    c.putImageData(prev.data, 0, 0);
    bump((n) => n + 1);
  };
  const doRedo = () => {
    const next = redo.current.pop();
    const c = next && ctxOf(next.id);
    if (!c || !next) return;
    undo.current.push({ id: next.id, data: c.getImageData(0, 0, W, H) });
    c.putImageData(next.data, 0, 0);
    bump((n) => n + 1);
  };

  const pos = (e: React.PointerEvent<HTMLCanvasElement>): Pt => {
    const r = e.currentTarget.getBoundingClientRect();
    // マウスは押している間 0.5 を返す。ペンだけ筆圧を使う
    const p = e.pointerType === "pen" ? e.pressure : 0.5;
    return { x: ((e.clientX - r.left) * W) / r.width, y: ((e.clientY - r.top) * H) / r.height, p };
  };

  const useColor = (c: string) => {
    setColor(c);
    setRecent((r) => [c, ...r.filter((x) => x !== c)].slice(0, 10));
  };

  // スポイト: 描いた層に色があればその色、無ければ下絵の色を拾う
  const pick = (q: Pt) => {
    const x = Math.round(q.x), y = Math.round(q.y);
    const c = g();
    const d = c?.getImageData(x, y, 1, 1).data;
    let rgb: number[] | null = d && (d[3] ?? 0) > 0 ? [d[0] ?? 0, d[1] ?? 0, d[2] ?? 0] : null;
    if (!rgb && underImg.current?.complete) {
      const t = document.createElement("canvas");
      t.width = W;
      t.height = H;
      const tg = t.getContext("2d");
      tg?.drawImage(underImg.current, 0, 0, W, H);
      const u = tg?.getImageData(x, y, 1, 1).data;
      if (u) rgb = [u[0] ?? 0, u[1] ?? 0, u[2] ?? 0];
    }
    if (rgb) useColor("#" + rgb.map((v) => v.toString(16).padStart(2, "0")).join(""));
    setTool("pen");
  };

  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const q = pos(e);
    if (tool === "picker") return pick(q);
    // 板の外へはみ出しても線を続ける。掴めない入力（作られた入力など）でも描くのは止めない
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* 掴めなくても描ける */
    }
    stroke.current = [q];
    last.current = q;
    snapshot();
  };

  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!last.current || !stroke.current.length) return;
    // 一度の move に複数の点が来る（ペンは細かく取れる）。全部使って線を滑らかにする
    // 一覧が空のこともある（ブラウザや作られた入力）。そのときは今の点だけを使う
    const co = e.nativeEvent.getCoalescedEvents?.();
    const evs = co && co.length ? co : [e.nativeEvent];
    const lc = live.current?.getContext("2d");
    for (const ev of evs) {
      const r = e.currentTarget.getBoundingClientRect();
      const raw = { x: ((ev.clientX - r.left) * W) / r.width, y: ((ev.clientY - r.top) * H) / r.height, p: ev.pointerType === "pen" ? ev.pressure : 0.5 };
      const prev: Pt = last.current;
      const q: Pt = assist.steady ? follow(prev, raw, assist.steadyAmount) : raw;
      if (lc) {
        lc.strokeStyle = lc.fillStyle = tool === "eraser" ? "#ff4fd8" : color;
        drawStroke(lc, [last.current, q], size, assist.pressure, assist.pressureMin);
      }
      stroke.current.push(q);
      last.current = q;
    }
  };

  const up = () => {
    const pts = stroke.current;
    stroke.current = [];
    last.current = null;
    const lc = live.current?.getContext("2d");
    lc?.clearRect(0, 0, W, H);
    const c = g();
    if (!c || !pts.length) return;
    // 線を整える: 角を丸めて、頭と尻を細くする。描いている間は手の動きのまま見せ、離したときに整えた線に置き換える
    const final = finishStroke(pts, assist);
    const t = document.createElement("canvas");
    t.width = W;
    t.height = H;
    const tg = t.getContext("2d");
    if (!tg) return;
    tg.strokeStyle = tg.fillStyle = color;
    drawStroke(tg, final, size, assist.pressure, assist.pressureMin);
    c.save();
    c.globalAlpha = alpha;
    c.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
    c.drawImage(t, 0, 0);
    c.restore();
    if (tool === "pen") useColor(color);
  };

  const clear = () => {
    snapshot();
    g()?.clearRect(0, 0, W, H);
  };

  // 書き出し: 下絵と描いた層を重ねた1枚と、描いた層だけの2通り
  const save = (withUnder: boolean) => {
    const t = document.createElement("canvas");
    t.width = W;
    t.height = H;
    const tg = t.getContext("2d");
    if (!tg) return;
    if (withUnder && underImg.current?.complete) tg.drawImage(underImg.current, 0, 0, W, H);
    // 見えているレイヤーを、下から順に不透明度どおりに重ねる
    for (const l of layers) {
      const c = canvases.current.get(l.id);
      if (!c || !l.visible) continue;
      tg.globalAlpha = l.opacity;
      tg.drawImage(c, 0, 0);
    }
    tg.globalAlpha = 1;
    const a = document.createElement("a");
    a.href = t.toDataURL("image/png");
    a.download = withUnder ? "paint-merged.png" : "paint-layer.png";
    a.click();
  };

  // レイヤーの操作。描いている先（選んだレイヤー）は、消したら残りの一番上へ移す
  const addLayer = () => {
    const id = nextLayer++;
    setLayers((ls) => [...ls, { id, name: `レイヤー ${id}`, visible: true, opacity: 1 }]);
    setActiveId(id);
  };
  const patch = (id: number, p: Partial<Layer>) => setLayers((ls) => ls.map((l) => (l.id === id ? { ...l, ...p } : l)));
  const removeLayer = (id: number) => {
    if (layers.length <= 1) return;
    const rest = layers.filter((l) => l.id !== id);
    setLayers(rest);
    canvases.current.delete(id);
    undo.current = undo.current.filter((u) => u.id !== id);
    redo.current = redo.current.filter((u) => u.id !== id);
    if (activeId === id) setActiveId((rest[rest.length - 1] as Layer).id);
  };
  const moveLayer = (id: number, d: -1 | 1) =>
    setLayers((ls) => {
      const i = ls.findIndex((l) => l.id === id), j = i + d;
      if (i < 0 || j < 0 || j >= ls.length) return ls;
      const out = [...ls];
      [out[i], out[j]] = [out[j] as Layer, out[i] as Layer];
      return out;
    });

  // 線の清書: 今のレイヤーのラフ線を送り、1本にまとめた線を新しいレイヤーに置く。元のラフは隠すだけで消さない
  const [inking, setInking] = useState(false);
  const inkLayer = async () => {
    const src = canvases.current.get(activeId);
    const from = layers.find((l) => l.id === activeId);
    if (!src || !from) return;
    setInking(true);
    try {
      const r = await fetch("/api/paint/ink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ png: src.toDataURL("image/png"), width: Math.max(1, Math.min(20, size * assist.inkWidth)), merge: assist.inkMerge, spur: assist.inkSpur }),
      });
      if (!r.ok) throw new Error(`清書に失敗した（${r.status}）`);
      const j = (await r.json()) as { png: string; strokes: number };
      const img = new Image();
      img.src = j.png;
      await img.decode();
      const id = nextLayer++;
      setLayers((ls) => {
        const i = ls.findIndex((l) => l.id === from.id);
        const out = ls.map((l) => (l.id === from.id ? { ...l, visible: false } : l));
        out.splice(i + 1, 0, { id, name: `${from.name}（清書）`, visible: true, opacity: 1 });
        return out;
      });
      setActiveId(id);
      // 新しいレイヤーの canvas は次の描画で作られる。作られてから絵を置く
      requestAnimationFrame(() => {
        const c = canvases.current.get(id)?.getContext("2d");
        if (c) {
          c.globalCompositeOperation = "source-over";
          c.drawImage(img, 0, 0, W, H);
          // 線の色は今のペンの色にする
          c.globalCompositeOperation = "source-in";
          c.fillStyle = color;
          c.fillRect(0, 0, W, H);
          c.globalCompositeOperation = "source-over";
        }
        bump((n) => n + 1);
      });
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setInking(false);
    }
  };

  // 切り出しと質感。下絵から一部（人物・色で選んだ所・部位）を切り出し、「残り」と「切り出し」の2枚のレイヤーにする。
  // 切り出したレイヤーだけ不透明度を下げればスライムの透け、質感を掛ければ金属・宝石などになる。下絵は隠すだけで消さない
  const [cutMode, setCutMode] = useState<"person" | "color" | "region">("color");
  const [cutColors, setCutColors] = useState<string[]>([]);
  const [cutTol, setCutTol] = useState(80);
  const [cutRegion, setCutRegion] = useState("skin");
  const [matKind, setMatKind] = useState("slime");
  const [matStrength, setMatStrength] = useState(0.6);
  const [working, setWorking] = useState("");

  const postJson = async <T,>(url: string, body: object): Promise<T> => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `失敗した（${r.status}）`);
    return (await r.json()) as T;
  };
  const putImage = (id: number, dataUrl: string) =>
    new Promise<void>((done) => {
      const img = new Image();
      img.onload = () => {
        requestAnimationFrame(() => {
          const c = canvases.current.get(id)?.getContext("2d");
          c?.clearRect(0, 0, W, H);
          c?.drawImage(img, 0, 0, W, H);
          bump((n) => n + 1);
          done();
        });
      };
      img.src = dataUrl;
    });

  const cutFromUnder = async () => {
    if (!underImg.current?.complete) return ctx.setError("下絵が無い（描いた絵を選んでから）");
    setWorking("切り出しています");
    try {
      const t = document.createElement("canvas");
      t.width = W;
      t.height = H;
      t.getContext("2d")?.drawImage(underImg.current, 0, 0, W, H);
      const j = await postJson<{ layer: string; rest: string; pixels: number }>("/api/paint/cut", {
        png: t.toDataURL("image/png"), mode: cutMode, colors: cutColors.join(","), tol: cutTol, region: cutRegion, person_only: true,
      });
      if (!j.pixels) throw new Error("選べた所が無い（色か幅を変える）");
      const restId = nextLayer++, partId = nextLayer++;
      setLayers((ls) => [{ id: restId, name: "残り", visible: true, opacity: 1 }, ...ls.slice(0, 0), { id: partId, name: "切り出し", visible: true, opacity: 1 }, ...ls]);
      setActiveId(partId);
      setUnderAlpha(0);
      await putImage(restId, j.rest);
      await putImage(partId, j.layer);
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setWorking("");
    }
  };

  const applyMaterial = async () => {
    const src = canvases.current.get(activeId);
    if (!src) return;
    setWorking("質感を掛けています");
    try {
      const j = await postJson<{ png: string }>("/api/paint/material", { png: src.toDataURL("image/png"), kind: matKind, strength: matStrength });
      snapshot();
      await putImage(activeId, j.png);
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setWorking("");
    }
  };

  // 空気感: 下絵と見えているレイヤーを重ねた絵全体に、光の筋・霞・粒などを掛け、一番上の新しいレイヤーに置く。
  // 隠せば元に戻る（下絵もほかのレイヤーも変えない）。決まりは docs/knowledge/atmosphere.md
  const [mood, setMood] = useState("holy");
  const [moodStrength, setMoodStrength] = useState(0.7);
  const [moodPrompt, setMoodPrompt] = useState("");
  const applyAtmosphere = async () => {
    setWorking("空気感を掛けています");
    try {
      const t = document.createElement("canvas");
      t.width = W;
      t.height = H;
      const tg = t.getContext("2d");
      if (!tg) return;
      tg.fillStyle = "#ffffff";
      tg.fillRect(0, 0, W, H);
      if (underImg.current?.complete && underAlpha > 0) {
        tg.globalAlpha = underAlpha;
        tg.drawImage(underImg.current, 0, 0, W, H);
      }
      for (const l of layers) {
        const c = canvases.current.get(l.id);
        if (!c || !l.visible) continue;
        tg.globalAlpha = l.opacity;
        tg.drawImage(c, 0, 0);
      }
      tg.globalAlpha = 1;
      const j = await postJson<{ png: string; prompt: string }>("/api/paint/atmosphere", { png: t.toDataURL("image/png"), mood, strength: moodStrength });
      const id = nextLayer++;
      const names: Record<string, string> = { holy: "神々しい光", dust: "ほこり", komorebi: "木漏れ日", underground: "地下", space: "宇宙", haze: "霞" };
      setLayers((ls) => [...ls, { id, name: `空気感（${names[mood] ?? mood}）`, visible: true, opacity: 1 }]);
      setActiveId(id);
      setMoodPrompt(j.prompt);
      await putImage(id, j.png);
    } catch (e) {
      ctx.setError((e as Error).message);
    } finally {
      setWorking("");
    }
  };

  const btn = (on: boolean) => `rounded border px-2 py-0.5 text-xs ${on ? "border-accent bg-accent font-bold text-ink" : "border-line"}`;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btn(tool === "pen")} onClick={() => setTool("pen")}>ペン</button>
        <button type="button" className={btn(tool === "eraser")} onClick={() => setTool("eraser")}>消しゴム</button>
        <button type="button" className={btn(tool === "picker")} onClick={() => setTool("picker")}>スポイト</button>
        <button type="button" className={btn(false)} onClick={doUndo} disabled={!undo.current.length}>戻す</button>
        <button type="button" className={btn(false)} onClick={doRedo} disabled={!redo.current.length}>やり直す</button>
        <button type="button" className={btn(false)} onClick={clear}>このレイヤーを消す</button>
        <button type="button" className={btn(false)} onClick={inkLayer} disabled={inking} title="重ねて描いたラフ線を1本の線にまとめ、新しいレイヤーに置く">
          {inking ? "清書中…" : "線を清書"}
        </button>
        <button type="button" className={btn(false)} onClick={() => save(true)}>重ねて保存</button>
        <button type="button" className={btn(false)} onClick={() => save(false)}>下絵なしで保存</button>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1">太さ<input type="range" min={1} max={80} value={size} onChange={(e) => setSize(+e.target.value)} />{size}</label>
        <label className="flex items-center gap-1">不透明度<input type="range" min={0.05} max={1} step={0.05} value={alpha} onChange={(e) => setAlpha(+e.target.value)} />{Math.round(alpha * 100)}%</label>
        <label className="flex items-center gap-1">下絵<input type="range" min={0} max={1} step={0.05} value={underAlpha} onChange={(e) => setUnderAlpha(+e.target.value)} />{Math.round(underAlpha * 100)}%</label>
      </div>
      <details className="rounded border border-line px-2 py-1 text-xs">
        <summary className="cursor-pointer">補助の設定（入れ切りと強さ。描いたとおりに残したいときは全部切る）</summary>
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          <label className="flex items-center gap-1"><input type="checkbox" checked={assist.steady} onChange={(e) => setAssist({ steady: e.target.checked })} />手ぶれ補正</label>
          <label className="flex items-center gap-1">強さ<input type="range" min={0.05} max={0.9} step={0.05} value={assist.steadyAmount} disabled={!assist.steady} onChange={(e) => setAssist({ steadyAmount: +e.target.value })} />{Math.round(assist.steadyAmount * 100)}</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={assist.round} onChange={(e) => setAssist({ round: e.target.checked })} />角を丸める</label>
          <label className="flex items-center gap-1">回数<input type="range" min={1} max={4} step={1} value={assist.roundPasses} disabled={!assist.round} onChange={(e) => setAssist({ roundPasses: +e.target.value })} />{assist.roundPasses}</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={assist.taper} onChange={(e) => setAssist({ taper: e.target.checked })} />入り抜き</label>
          <label className="flex items-center gap-1">量<input type="range" min={0.05} max={0.5} step={0.05} value={assist.taperAmount} disabled={!assist.taper} onChange={(e) => setAssist({ taperAmount: +e.target.value })} />{Math.round(assist.taperAmount * 100)}%</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={assist.pressure} onChange={(e) => setAssist({ pressure: e.target.checked })} />筆圧</label>
          <label className="flex items-center gap-1">最小の太さ<input type="range" min={0} max={0.9} step={0.05} value={assist.pressureMin} disabled={!assist.pressure} onChange={(e) => setAssist({ pressureMin: +e.target.value })} />{Math.round(assist.pressureMin * 100)}%</label>
          <span className="text-neutral-400">線の清書:</span>
          <label className="flex items-center gap-1">まとめる幅<input type="range" min={0.5} max={12} step={0.5} value={assist.inkMerge} onChange={(e) => setAssist({ inkMerge: +e.target.value })} />{assist.inkMerge}</label>
          <label className="flex items-center gap-1">落とすはみ出し<input type="range" min={0} max={30} step={1} value={assist.inkSpur} onChange={(e) => setAssist({ inkSpur: +e.target.value })} />{assist.inkSpur}</label>
          <label className="flex items-center gap-1">太さ<input type="range" min={0.2} max={2} step={0.1} value={assist.inkWidth} onChange={(e) => setAssist({ inkWidth: +e.target.value })} />×{assist.inkWidth}</label>
          <button type="button" className="rounded border border-line px-2" onClick={() => setAssist(ASSIST_OFF)}>補助を全部切る</button>
          <button type="button" className="rounded border border-line px-2" onClick={() => setAssist(ASSIST_DEFAULT)}>既定に戻す</button>
        </div>
      </details>
      <details className="rounded border border-line px-2 py-1 text-xs">
        <summary className="cursor-pointer">切り出しと質感（スライムの透け、金属・重厚・宝石・無機質・汚れ）</summary>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <label className="flex items-center gap-1">選び方
            <select className="rounded border border-line bg-transparent" value={cutMode} onChange={(e) => setCutMode(e.target.value as "person" | "color" | "region")}>
              <option value="color">色で選ぶ（人物の中だけ）</option>
              <option value="person">人物全体</option>
              <option value="region">部位</option>
            </select>
          </label>
          {cutMode === "color" && (
            <>
              <span>色:</span>
              {cutColors.map((c) => (
                <button key={c} type="button" title={`${c}（押すと外す）`} className="h-4 w-4 rounded-sm border border-line" style={{ background: c }}
                  onClick={() => setCutColors((cs) => cs.filter((x) => x !== c))} />
              ))}
              <button type="button" className="rounded border border-line px-1" onClick={() => setCutColors((cs) => (cs.includes(color) ? cs : [...cs, color]))}>
                今の色を足す
              </button>
              <span className="text-neutral-400">（スポイトで下絵の色を拾ってから。光の所と陰の所など、色が離れていれば複数足す）</span>
              <label className="flex items-center gap-1">幅<input type="range" min={10} max={150} step={5} value={cutTol} onChange={(e) => setCutTol(+e.target.value)} />{cutTol}</label>
            </>
          )}
          {cutMode === "region" && (
            <select className="rounded border border-line bg-transparent" value={cutRegion} onChange={(e) => setCutRegion(e.target.value)}>
              <option value="skin">肌（顔・腕・脚）</option><option value="hair">髪</option><option value="clothes">服</option>
              <option value="upper">上の服</option><option value="lower">下の服</option><option value="shoes">靴</option>
            </select>
          )}
          <button type="button" className="rounded bg-accent px-2 font-bold text-ink" disabled={!!working || (cutMode === "color" && !cutColors.length)} onClick={cutFromUnder}>
            下絵から切り出す
          </button>
          <span className="text-neutral-400">→「残り」と「切り出し」のレイヤーになる。スライムの透けは「切り出し」の不透明度を下げる</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <label className="flex items-center gap-1">質感
            <select className="rounded border border-line bg-transparent" value={matKind} onChange={(e) => setMatKind(e.target.value)}>
              <option value="slime">透明感（スライム）</option><option value="metal">金属感</option><option value="heavy">重厚感</option>
              <option value="gem">宝石感</option><option value="inorganic">無機質感</option><option value="dirt">汚れ</option>
            </select>
          </label>
          <label className="flex items-center gap-1">強さ<input type="range" min={0.05} max={1} step={0.05} value={matStrength} onChange={(e) => setMatStrength(+e.target.value)} />{Math.round(matStrength * 100)}%</label>
          <button type="button" className="rounded border border-line px-2" disabled={!!working} onClick={applyMaterial}>今のレイヤーに掛ける</button>
          {working && <span className="text-neutral-400">{working}…</span>}
        </div>
      </details>
      <details className="rounded border border-line px-2 py-1 text-xs">
        <summary className="cursor-pointer">空気感（神々しい光・ほこり・木漏れ日・地下・宇宙・霞）</summary>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <select className="rounded border border-line bg-transparent" value={mood} onChange={(e) => setMood(e.target.value)} aria-label="空気感">
            <option value="holy">神々しい光（光の筋・にじみ・光の粒）</option>
            <option value="dust">ほこりっぽい（黄土の霞・鋭い筋・粒）</option>
            <option value="komorebi">木漏れ日（光の斑点・緑の木陰）</option>
            <option value="underground">地下（周りを沈め、火の光だけ暖かい）</option>
            <option value="space">宇宙（暗く冷たく、星と星雲、色の縁取り）</option>
            <option value="haze">霞（遠くほど空の色）</option>
          </select>
          <label className="flex items-center gap-1">強さ<input type="range" min={0.05} max={1} step={0.05} value={moodStrength} onChange={(e) => setMoodStrength(+e.target.value)} />{Math.round(moodStrength * 100)}%</label>
          <button type="button" className="rounded border border-line px-2" disabled={!!working} onClick={applyAtmosphere}>絵全体に掛ける</button>
          <span className="text-neutral-400">→ 一番上の新しいレイヤーになる。隠せば元に戻る</span>
          {moodPrompt && <span className="w-full text-neutral-400">描くときに足す言葉: <code>{moodPrompt}</code></span>}
        </div>
      </details>
      <div className="flex flex-wrap items-center gap-1">
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} aria-label="色を選ぶ" />
        {PRESET.map((c) => (
          <button key={c} type="button" aria-label={c} title={c} onClick={() => useColor(c)}
            className={`h-5 w-5 rounded-sm border ${c === color ? "border-accent" : "border-line"}`} style={{ background: c }} />
        ))}
        {recent.length > 0 && <span className="ml-2 text-xs text-neutral-400">最近</span>}
        {recent.map((c) => (
          <button key={"r" + c} type="button" aria-label={c} title={c} onClick={() => setColor(c)}
            className="h-5 w-5 rounded-sm border border-line" style={{ background: c }} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-xs">
        <span className="text-neutral-400">レイヤー（上ほど手前）</span>
        {[...layers].reverse().map((l) => (
          <span key={l.id} className={`flex items-center gap-1 rounded border px-1 ${l.id === activeId ? "border-accent" : "border-line"}`}>
            <input type="checkbox" checked={l.visible} aria-label={`${l.name}を見せる`} onChange={(e) => patch(l.id, { visible: e.target.checked })} />
            <button type="button" className={l.id === activeId ? "font-bold" : ""} onClick={() => setActiveId(l.id)}>{l.name}</button>
            <input type="range" min={0} max={1} step={0.05} value={l.opacity} aria-label={`${l.name}の不透明度`} className="w-14"
              onChange={(e) => patch(l.id, { opacity: +e.target.value })} />
            <button type="button" aria-label="上へ" onClick={() => moveLayer(l.id, 1)}>▲</button>
            <button type="button" aria-label="下へ" onClick={() => moveLayer(l.id, -1)}>▼</button>
            <button type="button" aria-label="消す" disabled={layers.length <= 1} onClick={() => removeLayer(l.id)}>×</button>
          </span>
        ))}
        <button type="button" className={btn(false)} onClick={addLayer}>＋ レイヤー</button>
      </div>
      <div className="relative min-h-0 flex-1">
        <div className="relative mx-auto h-full" style={{ aspectRatio: `${W} / ${H}`, maxWidth: "100%" }}>
          <div className="absolute inset-0 bg-white" />
          {under && <img ref={underImg} src={under} alt="下絵" crossOrigin="anonymous" className="absolute inset-0 h-full w-full" style={{ opacity: underAlpha }} />}
          {layers.map((l) => (
            <canvas key={l.id} width={W} height={H} className="absolute inset-0 h-full w-full"
              ref={(el) => { if (el) canvases.current.set(l.id, el); }}
              style={{ opacity: l.opacity, visibility: l.visible ? "visible" : "hidden" }} />
          ))}
          <canvas ref={live} width={W} height={H} className="absolute inset-0 h-full w-full touch-none"
            style={{ opacity: alpha, cursor: tool === "picker" ? "copy" : "crosshair" }}
            onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
        </div>
      </div>
    </div>
  );
}
