"""全部の加工と修正を、本物の絵の模型で描いた絵に、アプリと同じ関数を通して掛け、前と後の絵と数字を残す
（.github/workflows/finish-verify.yml）。手元の試験の模型は重みが乱数なので、効いたか・崩れたかはここでしか見られない。

    python -m chatdraw.finish_verify draw <出す所>                    絵の模型で 1 枚描く（before.png）
    python -m chatdraw.finish_verify apply <絵> <出す所> <項目>...    項目を 1 つずつ掛ける

項目: fin:<finishers.REGISTRY の名前>、combo:<shortcuts.COMBOS の id の後ろ>、app:<lineart|pixel|nobg|transparent|upscale2x>、
fix:<赤ペンの指示の文>（Studio.fix）、req:<修正依頼の名前>（fixrequests の一覧）。
囲みの要る物（around、fix、req）は顔の周りの四角（BOX）を囲みにし、囲みの外の変わった画素も数える。
数字: 変わった画素（色の差が 8 を超える画素）、目で分かる変わり（差が 32 を超える画素）、差の平均、囲みの外の変わった画素、
アプリが出す知らせの文。前（左）と後（右）を並べた絵を項目ごとに 1 枚ずつ置く。
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

MODEL = os.environ.get("CD_VERIFY_MODEL", "cagliostrolab/animagine-xl-4.0")
# 試しの絵の頼み（私の推測で決めた、顔・手・服・背景の入る 1 人の絵）
PROMPT = os.environ.get("CD_VERIFY_PROMPT", "1girl, solo, long hair, school uniform, smile, upper body, looking at viewer, "
                        "hand up, classroom, window, masterpiece, best quality")
SEED = int(os.environ.get("CD_VERIFY_SEED", "1234"))
SIZE = (832, 1216)


def _painter():
    from chatdraw.engine import Painter
    return Painter(MODEL, steps=int(os.environ.get("CD_VERIFY_STEPS", "24")), size=SIZE)


def box_for(size):
    """囲み: 絵の上の真ん中（顔の入りやすい所）の四角。左・上・右・下"""
    w, h = size
    return (int(w * 0.3), int(h * 0.08), int(w * 0.7), int(h * 0.38))


def stats(before, after, mask=None) -> dict:
    import numpy as np
    a = np.asarray(before.convert("RGB")).astype(int)
    b = np.asarray(after.convert("RGB").resize(before.size)).astype(int)
    d = np.abs(a - b).max(2)
    out = dict(changed=int((d > 8).sum()), visible=int((d > 32).sum()), mean=round(float(np.abs(a - b).mean()), 3),
               pixels=int(d.size), size_after=list(after.size))
    if mask is not None:
        m = np.asarray(mask.convert("L").resize(before.size)) >= 128
        out["outside_changed"] = int((d[~m] > 0).sum())
        out["inside_changed"] = int((d[m] > 8).sum())
    return out


def side_by_side(before, after, path: Path):
    from PIL import Image
    a = before.convert("RGB")
    b = after.convert("RGBA")
    if b.size != a.size:
        b = b.resize(a.size, Image.LANCZOS)
    bg = Image.new("RGBA", a.size, (200, 200, 200, 255))   # 透過の結果は灰色の地で見せる
    bg.alpha_composite(b)
    pair = Image.new("RGB", (a.width * 2 + 8, a.height), (255, 255, 255))
    pair.paste(a, (0, 0))
    pair.paste(bg.convert("RGB"), (a.width + 8, 0))
    pair.save(path, quality=92)


def draw(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    p = _painter()
    t = time.time()
    img = p.paint(PROMPT, SEED, size=SIZE)
    img.save(out / "before.png")
    (out / "before.json").write_text(json.dumps(dict(model=MODEL, prompt=PROMPT, seed=SEED, size=SIZE,
                                                     seconds=round(time.time() - t, 1)), ensure_ascii=False), encoding="utf-8")
    print("描きました", out / "before.png", round(time.time() - t, 1), "秒", flush=True)
    return 0


class _Win:
    """app の関数の中で使う、模型を使わない加工の本体（app.py の make_lineart・make_pixel・remove_background・make_transparent・
    upscale_canvas と同じ関数を呼ぶ）"""

    @staticmethod
    def app(kind: str, src):
        from chatdraw import postfx
        if kind == "lineart":
            return postfx.lineart(src)
        if kind == "pixel":
            return postfx.enlarge(postfx.pixel_art(src, long=128, colors=24), src.size)
        if kind == "nobg":
            return postfx.paper_to_alpha(src)
        if kind == "transparent":
            import tempfile
            from chatdraw import paths
            paths.use_tools_gen()
            import layers as gen_layers
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "a.png"
                src.save(p)
                return gen_layers.anime_cut(str(p))
        if kind == "upscale2x":
            from chatdraw import upscale
            return upscale.upscale(src, 2)
        raise KeyError(kind)


def apply_one(item: str, src, painter, studio) -> tuple:
    """(結果の絵, 囲み, 知らせ)。アプリと同じ関数を通す"""
    from PIL import Image
    from chatdraw import finishers
    kind, _, name = item.partition(":")
    mask = None
    if kind in ("fix", "req") or name == "around":
        mask = Image.new("L", src.size, 0)
        mask.paste(255, box_for(src.size))
    finishers.use_painter(painter)
    finishers.use_source(PROMPT)   # 描いたときの言葉（アプリの fix_source と同じ）
    if kind == "fin":
        out = finishers.run_chain([name], src, mask)   # finish_with(background=True) → finish_chain → run_chain
        note = finishers.chain_note()
        if name.startswith("style_"):
            from chatdraw import restyle
            note = restyle.note() + note
        if all(q.get("rejected") for q in finishers.LAST_CHAIN):
            note = "【採らない】" + note
        return out, mask, note
    if kind == "combo":
        from chatdraw import shortcuts
        steps = {sid: st for sid, _l, st, _t in shortcuts.COMBOS}["combo:" + name]
        out = finishers.run_chain(list(steps), src, mask)
        return out, mask, finishers.chain_note()
    if kind == "app":
        return _Win.app(name, src), mask, ""
    if kind in ("fix", "req"):
        from chatdraw import fixrequests
        note = name
        if kind == "req":
            req = fixrequests.lookup(name)
            if req and req.get("tool"):
                from chatdraw import edittools
                fn = {"erase": edittools.erase, "smooth": edittools.smooth_lines, "despeckle": edittools.despeckle}[req["tool"]]
                return fn(src, mask), mask, ""
        said: list[str] = []
        _prompts, path = studio.fix(src, [(mask, note)], random.randrange(0, 2_000_000_000), on_status=said.append)
        layer = Image.open(path).convert("RGBA")
        done = src.convert("RGBA")
        done.alpha_composite(layer)
        keep = [s for s in said if s.startswith(("渡した言葉", "赤ペンの指示のうち", "崩れ", "確かめました", "描けた"))]
        return done.convert("RGB"), mask, " / ".join(keep)
    raise KeyError(item)


def apply(src_path: Path, out: Path, items: list[str]) -> int:
    from PIL import Image
    from chatdraw.engine import Studio, Words
    out.mkdir(parents=True, exist_ok=True)
    src = Image.open(src_path).convert("RGB")
    need = any(i.startswith(("fin:style_", "fin:refine", "fix:", "req:")) for i in items)
    painter = _painter() if need else None
    studio = Studio(Words(Path("")), painter, out / "saved") if need else None
    rows = []
    for item in items:
        t = time.time()
        row = dict(item=item)
        try:
            res, mask, note = apply_one(item, src, painter, studio)
            row.update(stats(src, res, mask), note=note)
            safe = item.replace(":", "-").replace("/", "_")
            side_by_side(src, res, out / f"{safe}.jpg")
            res.save(out / f"{safe}.png")
            row["file"] = f"{safe}.jpg"
        except Exception as e:   # noqa: BLE001  1 つが落ちても残りを掛け、落ちた理由を残す
            row["error"] = f"{type(e).__name__}: {e}"
            row["trace"] = traceback.format_exc()[-1500:]
        row["seconds"] = round(time.time() - t, 1)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "trace"}, ensure_ascii=False), flush=True)
    (out / f"verify-{os.environ.get('CD_VERIFY_TAG', 'all')}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "draw":
        return draw(Path(argv[1]))
    if argv and argv[0] == "apply":
        return apply(Path(argv[1]), Path(argv[2]), argv[3:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
