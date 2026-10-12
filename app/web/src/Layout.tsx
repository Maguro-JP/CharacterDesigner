import { useRef, useState } from "react";
import type { LayoutNode } from "./api";
import { PANELS, type Ctx } from "./panels";

// 配置のデータ（split と tabs の入れ子）どおりに板を並べる。仕切りを掴んで動かすと比率が変わり、onChange で保存する。
// 知らない板の名前でも落とさず、その場に「無い板」と出す（配置を AI や手で書き換えても画面を真っ白にしない）
function Panel({ kind, ctx }: { kind: string; ctx: Ctx }) {
  const p = PANELS[kind];
  return (
    <section className="flex h-full min-h-0 flex-col rounded border border-line bg-panel">
      <h2 className="border-b border-line px-3 py-1.5 text-sm font-bold">{p?.title ?? kind}</h2>
      <div className="min-h-0 flex-1 overflow-auto p-3">{p ? p.render(ctx) : <p className="text-sm text-signal">「{kind}」という板は無い</p>}</div>
    </section>
  );
}

function Tabs({ nodes, ctx, path, onSizes }: { nodes: LayoutNode[]; ctx: Ctx; path: number[]; onSizes: OnSizes }) {
  const [cur, setCur] = useState(0);
  const title = (n: LayoutNode) => (n.type === "panel" ? (PANELS[n.panel]?.title ?? n.panel) : "まとめ");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex gap-1 overflow-x-auto" role="tablist">
        {nodes.map((n, k) => (
          <button key={k} type="button" role="tab" aria-selected={k === cur} onClick={() => setCur(k)}
            className={`shrink-0 whitespace-nowrap rounded-t border border-b-0 px-3 py-1 text-xs ${k === cur ? "border-line bg-panel font-bold" : "border-transparent text-neutral-400"}`}>
            {title(n)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {nodes[Math.min(cur, nodes.length - 1)] && (
          <Node node={nodes[Math.min(cur, nodes.length - 1)] as LayoutNode} ctx={ctx} path={[...path, cur]} onSizes={onSizes} />
        )}
      </div>
    </div>
  );
}

type OnSizes = (path: number[], sizes: number[], done: boolean) => void;

function Split({ node, ctx, path, onSizes }: { node: Extract<LayoutNode, { type: "split" }>; ctx: Ctx; path: number[]; onSizes: OnSizes }) {
  const box = useRef<HTMLDivElement>(null);
  const row = node.direction === "row";
  // 仕切り k を掴んで動かす。隣り合う2つの比率だけを変え、どちらも 8% より小さくしない
  const drag = (k: number) => (e: React.PointerEvent) => {
    const el = box.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const total = row ? rect.width : rect.height;
    const start = row ? e.clientX : e.clientY;
    const base = [...node.sizes];
    let last = base;
    const move = (ev: PointerEvent) => {
      const d = ((row ? ev.clientX : ev.clientY) - start) / total;
      const pair = (base[k] ?? 0) + (base[k + 1] ?? 0);
      const a = Math.min(pair - 0.08, Math.max(0.08, (base[k] ?? 0) + d));
      last = base.map((s, i) => (i === k ? a : i === k + 1 ? pair - a : s));
      onSizes(path, last, false);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      onSizes(path, last, true);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div ref={box} className={`flex h-full min-h-0 w-full ${row ? "flex-row" : "flex-col"}`}>
      {node.children.map((c, k) => (
        <div key={k} className="contents">
          <div className="min-h-0 min-w-0" style={{ flex: `${node.sizes[k]} 1 0` }}>
            <Node node={c} ctx={ctx} path={[...path, k]} onSizes={onSizes} />
          </div>
          {k < node.children.length - 1 && (
            <div role="separator" aria-orientation={row ? "vertical" : "horizontal"} onPointerDown={drag(k)}
              className={`shrink-0 bg-transparent hover:bg-accent/40 ${row ? "w-1.5 cursor-col-resize" : "h-1.5 cursor-row-resize"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

function Node({ node, ctx, path, onSizes }: { node: LayoutNode; ctx: Ctx; path: number[]; onSizes: OnSizes }) {
  if (node.type === "panel") return <Panel kind={node.panel} ctx={ctx} />;
  if (node.type === "tabs") return <Tabs nodes={node.children} ctx={ctx} path={path} onSizes={onSizes} />;
  return <Split node={node} ctx={ctx} path={path} onSizes={onSizes} />;
}

// 狭い画面（スマートフォン）では仕切りを使わず、板を縦に1列で並べる（横にはみ出させない）
export function flatPanels(node: LayoutNode): string[] {
  return node.type === "panel" ? [node.panel] : node.children.flatMap(flatPanels);
}

export default function LayoutView({ root, ctx, narrow, onSizes }: { root: LayoutNode; ctx: Ctx; narrow: boolean; onSizes: OnSizes }) {
  if (narrow) {
    return (
      <div className="space-y-3">
        {flatPanels(root).map((k) => (
          <div key={k} className={k === "canvas" || k === "paint" ? "h-[70vh]" : ""}>
            <Panel kind={k} ctx={ctx} />
          </div>
        ))}
      </div>
    );
  }
  return <Node node={root} ctx={ctx} path={[]} onSizes={onSizes} />;
}
