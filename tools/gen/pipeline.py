"""人物の絵を工程（フェーズ）に分けて描かせる。工程ごとに確かめ、落ちたらその工程だけを種を変えて描き直す。

1 回で全部を通そうとすると、手が崩れただけで体から描き直しになり、良かった体も失った。
工程の出力と確かめの結果は <出力>/state.json に残り、途中から再開できる。落ちた絵も消さずに残す（なぜ落ちたかを見るため）。

  工程   入力           出力                 確かめ（落ちたらこの工程だけやり直す）
  base   設定資料集      人形の下絵と奥行き    体の決まり（股・肘・膝）
  draw   base           全身の絵             下絵との釣り合いのずれ、頭身、端の切れ、浮いた塊
  face   draw           顔を描き直した絵      目の左右のそろい
  hands  face           手を描き直した絵      手の指（MediaPipe）
  check  hands          検品の記録           自動の検品全部。ここから先は検品担当（checker）と利用者の目

  PYTHONPATH=.cache/gen/lib python3 tools/gen/pipeline.py run <id> <出力> [--view front] [--from draw] [--only hands] [--tries 3]
  python3 tools/gen/pipeline.py status <出力>

試すたびに <出力>/progress.html（作業の様子の頁）を書き直す。工程ごとに試した絵を全部、通ったか・落ちた理由と並べる。

描く模型は 1 つの処理の中で 1 回だけ読む（並べて動かすとメモリが足りず強制終了された）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402

PHASES = ["base", "draw", "face", "hands", "check"]
# 工程ごとの描く強さ。draw の奥行きの縛りは描き始めだけ（全部で縛ると塗りが平たくなり、縛らないと腕を長く描いた）
DRAW = dict(strength=0.85, depth_scale=0.8, depth_end=0.4)
FACE_STRENGTH = 0.45
HAND_STRENGTH = 0.6


def _load(out: Path) -> dict:
    p = out / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"phases": {}}


def _save(out: Path, st: dict) -> None:
    (out / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1, default=float), encoding="utf-8")


def _extent(path: str):
    import numpy as np
    from PIL import Image
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    fg = np.abs(rgb - rgb[2, 2]).sum(2) > 40
    rows = np.nonzero(fg.sum(1) > 3)[0]
    return int(rows[0]), int(rows[-1])


# ---- 工程 ----

def phase_base(ident, out, view, seed, st):
    import os
    import subprocess
    plan = bible.turnaround_plan(ident, str(out / "base"), seed)
    if st.get("heads"):
        # 頭身を比べる実験（sweep）では、ジャンルの既定の代わりに決めた頭身で人形を作る
        cmd = plan["base_cmd"]
        if "--heads" in cmd:
            i = cmd.index("--heads")
            del cmd[i:i + 2]
        cmd += ["--heads", str(st["heads"])]
    env = {**os.environ, "PYTHONPATH": str(bible.ROOT / ".cache/engine/bpy")}
    subprocess.run(plan["base_cmd"] + ["--depth"], check=True, env=env, cwd=bible.ROOT, capture_output=True)
    f = str(out / "base" / f"base-{view}.png")
    return {"file": f, "depth": str(out / "base" / f"base-{view}-depth.png")}


def check_base(res, ident, view):
    import joints
    import qc
    if view != "front":
        return []
    top, bottom = _extent(res["file"])
    st = qc.structure(joints.find(res["file"]), top, bottom)
    # 手首の決まりは人形の腕の開きで外れやすく、描く模型が直すので、下絵では股・肘・膝だけを見る
    return [f"{k} {v}" for k, v in st["off"].items() if not k.startswith("wrist")]


def phase_draw(ident, out, view, seed, st):
    base = st["phases"]["base"]["result"]
    plan = bible.turnaround_plan(ident, str(out / "base"))["views"][view]
    d = out / "draw" / f"seed-{seed}"
    names = bible.draw(ident, str(d), 1, seed, base=base["file"], depth=base["depth"], designing=True,
                       items=[], pose=plan["pose"], **DRAW)
    return {"file": str(d / names[0])}


def check_draw(res, ident, view, st):
    import joints
    import qc
    g = bible.genre(ident)
    pts = joints.find(res["file"])
    base_pts = joints.find(st["phases"]["base"]["result"]["file"])
    bad = [f"釣り合い {k} {v}" for k, v in qc.proportion_drift(qc.proportions(base_pts), qc.proportions(pts))["off"].items()]
    auto = qc.auto_check(res["file"], "", tuple(g["heads_tall"]))
    keep = ("heads_tall", "edge_cut", "floating", "seams", "fixed_restriction", "extra_eyes")
    bad += [json.dumps(p, ensure_ascii=False) for p in auto["problems"] if any(k in p for k in keep)]
    res["auto"] = auto
    return bad


def phase_face(ident, out, view, seed, st):
    import detail
    src = st["phases"]["draw"]["result"]["file"]
    pos, neg = bible.prompt(ident, framing="")
    f = out / "face" / f"seed-{seed}.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    r = detail.detail(src, str(f), pos, neg + ", scar, facial mark", strength=FACE_STRENGTH, seed=seed)
    return {"file": str(f), "box": r.get("box")}


def check_face(res, ident, view, st):
    import measure
    import qc
    if view == "back":
        return []
    eye = qc.eye_mismatch(measure.measure(res["file"])["eyes"])
    if not eye["readable"]:
        return ["目が読めない"]
    return [f"目 {json.dumps(eye, ensure_ascii=False, default=float)}"] if eye["mismatch"] else []


def phase_hands(ident, out, view, seed, st):
    import detail
    import joints
    src = st["phases"]["face"]["result"]["file"]
    pos, neg = bible.prompt(ident, framing="")
    pts = {q["name"]: q for q in joints.find(src)}
    f = out / "hands" / f"seed-{seed}.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    cur = src
    for i, side in enumerate(("left", "right")):
        w = pts.get(f"{side}_wrist")
        if not w:
            continue
        x, y = int(w["x"]), int(w["y"])
        # 手首の点から指先の側へ広めに取る（手首だけで枠を作ると指先が枠の外に出た）
        box = (x - 80, y - 50, x + 80, y + 110)
        detail.detail(cur, str(f), "relaxed hand at side, fingers together, slightly curled, five fingers, " + pos,
                      neg + ", claws, spread fingers, long fingers", strength=HAND_STRENGTH, seed=seed + i, box=box,
                      words=detail.HAND_WORDS, extra_negative=detail.HAND_NEGATIVE)
        cur = str(f)
    return {"file": cur}


def check_hands(res, ident, view, st):
    import joints
    import qc
    from PIL import Image
    h = qc.hands_auto(joints.find(res["file"]), Image.open(res["file"]).convert("RGB"))
    if not h["readable"]:
        return []   # 手が読めない（後ろ向き・隠れている）ときは目で見る
    return [f"手 {json.dumps(h['bad'], ensure_ascii=False, default=float)}"] if h["bad"] else []


def phase_check(ident, out, view, seed, st):
    import qc
    f = st["phases"]["hands"]["result"]["file"]
    g = bible.genre(ident)
    return {"file": f, "auto": qc.auto_check(f, "", tuple(g["heads_tall"]))}


def check_check(res, ident, view, st):
    return [json.dumps(p, ensure_ascii=False, default=float) for p in res["auto"]["problems"]]


# 検品（check）で見つかった崩れの種類 → 戻る工程（docs/knowledge/pipeline-flow.md の表）。そこから先だけをやり直す
ROUTE = {"heads_tall": "base", "structure": "base", "drift": "draw", "edge_cut": "draw", "floating": "draw",
         "seams": "draw", "fixed_restriction": "draw", "extra_eyes": "face", "eyes": "face", "measure": "face",
         "hands": "hands"}


def route(bad: list[str]) -> str | None:
    """検品の崩れから、最も前の戻り先を選ぶ（前の工程を直せば後ろも描き直しになるので、一番前から）"""
    hits = [ph for b in bad for k, ph in ROUTE.items() if k in b]
    return min(hits, key=PHASES.index) if hits else None


RUN = {"base": phase_base, "draw": phase_draw, "face": phase_face, "hands": phase_hands, "check": phase_check}
CHECK = {"base": lambda r, i, v, s: check_base(r, i, v), "draw": check_draw, "face": check_face,
         "hands": check_hands, "check": check_check}
# 落ちたとき種を変えてやり直す工程（base と check は種で結果が変わらないのでやり直さない）
RETRY = {"draw", "face", "hands"}


NAMES = {"base": "下絵（人形）", "draw": "全身を描く", "face": "顔を描き直す", "hands": "手を描き直す", "check": "検品"}


def board(out: Path, st: dict) -> Path:
    """作業の様子の 1 枚の頁（<出力>/progress.html）。工程ごとに、試した絵を全部、通ったか・落ちた理由と一緒に並べる。
    一度に完成だけを出すと、どこで何が直されたのか、なぜ落ちたのかが人から見えなかった。試すたびに書き直す"""
    import html
    e = html.escape
    rows = []
    for ph in PHASES:
        rec = st["phases"].get(ph)
        if not rec:
            rows.append(f'<section><h2>{NAMES[ph]}<small>まだ</small></h2></section>')
            continue
        cells = []
        for t in rec["tries"]:
            f = t.get("file")
            img = f'<a href="{e(Path(f).relative_to(out).as_posix())}"><img src="{e(Path(f).relative_to(out).as_posix())}" loading="lazy"></a>' if f and Path(f).exists() and Path(f).is_relative_to(out) else ""
            verdict = "通る" if not t["bad"] else "落ちる"
            why = "".join(f"<li>{e(b)}</li>" for b in t["bad"])
            cells.append(f'<figure class="{"ok" if not t["bad"] else "ng"}">{img}<figcaption>種 {t["seed"]}・{t["sec"]} 秒・{verdict}<ul>{why}</ul></figcaption></figure>')
        mark = "通った" if rec.get("ok") else ("止まった" if st.get("stopped") == ph else "やり直し中")
        rows.append(f'<section><h2>{NAMES[ph]}<small>{mark}・{len(rec["tries"])} 回</small></h2><div class="tries">{"".join(cells)}</div></section>')
    page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>作業の様子</title><meta http-equiv="refresh" content="30"><style>'
            'body{font-family:sans-serif;background:#fbfaf7;color:#141313;margin:0;padding:16px}h1{font-size:22px}'
            'section{border-top:2px solid #141313;padding:8px 0}h2{font-size:17px;margin:4px 0}h2 small{color:#d23a26;margin-left:8px}'
            '.tries{display:flex;gap:12px;overflow-x:auto}figure{margin:0;min-width:260px;max-width:320px}'
            'img{width:100%;border:3px solid #ccc;background:#fff}.ok img{border-color:#2a7}.ng img{border-color:#d23a26}'
            'figcaption{font-size:13px}ul{margin:4px 0;padding-left:18px;color:#a33}</style>'
            f'<h1>{e(st.get("id", ""))} の作業の様子（{e(st.get("view", ""))}）</h1>' + "".join(rows))
    p = out / "progress.html"
    p.write_text(page, encoding="utf-8")
    return p


def run(ident: str, outdir: str, view: str = "front", start: str | None = None, only: str | None = None,
        tries: int = 3, seed: int = 0, rewinds: int = 2, until: str | None = None, heads: float | None = None) -> dict:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    st = _load(out)
    st.update(id=ident, view=view)
    if heads:
        st["heads"] = heads
    todo = [only] if only else PHASES[PHASES.index(start):] if start else PHASES
    if until:
        todo = todo[:todo.index(until) + 1] if until in todo else todo
    for ph in todo:
        rec = st["phases"].setdefault(ph, {"tries": []})
        for k in range(tries if ph in RETRY else 1):
            s = seed + len(rec["tries"])
            t = time.time()
            res = RUN[ph](ident, out, view, s, st)
            bad = CHECK[ph](res, ident, view, st)
            rec["tries"].append({"seed": s, "file": res.get("file"), "bad": bad, "sec": round(time.time() - t)})
            rec["result"] = res
            rec["ok"] = not bad
            _save(out, st)
            board(out, st)
            print(f"{ph} 種 {s}: {'通る' if not bad else '落ちる ' + '; '.join(bad)}", flush=True)
            if not bad:
                break
        if not rec["ok"] and ph != "check":
            # 落ちたまま次へ進むと、後の工程が崩れた絵を土台に描く。止めて、どこで落ちたかを返す
            st["stopped"] = ph
            _save(out, st)
            board(out, st)
            return st
    chk = st["phases"].get("check", {})
    back = route(chk["tries"][-1]["bad"]) if chk.get("tries") and not chk.get("ok") and not only else None
    if back and rewinds > 0:
        # 検品で落ちたら、崩れを受け持つ工程まで戻って、そこから先だけをやり直す（全部を描き直さない）
        st.setdefault("rewinds", []).append({"to": back, "because": chk["tries"][-1]["bad"]})
        _save(out, st)
        print(f"検品で落ちたので {back} から先をやり直す", flush=True)
        return run(ident, outdir, view, back, None, tries, seed, rewinds - 1, until, heads)
    st.pop("stopped", None)
    _save(out, st)
    board(out, st)
    return st


def status(outdir: str) -> dict:
    st = _load(Path(outdir))
    return {ph: {"ok": r.get("ok"), "tries": len(r["tries"]), "last": r["tries"][-1] if r["tries"] else None}
            for ph, r in st.get("phases", {}).items()} | {"stopped": st.get("stopped")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("id"); s.add_argument("out"); s.add_argument("--view", default="front")
    s.add_argument("--from", dest="start", choices=PHASES); s.add_argument("--only", choices=PHASES)
    s.add_argument("--tries", type=int, default=3); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--until", choices=PHASES, help="この工程まで進めて止める")
    s.add_argument("--heads", type=float, help="人形の頭身（実験用。省くとジャンルの既定）")
    s = sub.add_parser("status"); s.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "run":
        import design  # noqa: F401  模型を勝手に取りに行かない設定（HF_HUB_OFFLINE）を diffusers より先に効かせる
        r = run(a.id, a.out, a.view, a.start, a.only, a.tries, a.seed, until=a.until, heads=a.heads)
        print(json.dumps(status(a.out), ensure_ascii=False, indent=1, default=float))
        sys.exit(1 if r.get("stopped") else 0)
    print(json.dumps(status(a.out), ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
