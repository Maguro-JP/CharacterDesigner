"""頼み 1 件を、指定の模型で 1 枚描く（GitHub Actions の draw-one.yml で流す）。

    python -m chatdraw.draw_one <置き場>   （頼みは config/draw-request.json）

手元に置けない大きな模型（FLUX、Z-Image など）を、描く仕組み（Painter）と同じ経路で試すために使う。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    req = json.loads(Path("config/draw-request.json").read_text(encoding="utf-8"))
    if req.get("mode") == "twostage":
        # 段は環境変数 DRAW_STAGE（compose、finish、all）で選ぶ。Actions では段ごとに別のジョブにして、
        # 1 つのジョブが打ち切られても、前の段の絵は draw-results に残る
        import os
        from chatdraw.twostage import draw
        stage = os.environ.get("DRAW_STAGE", "all")
        # 頼みの composition に、立体の人形（関節の可動域を検査した姿勢）を撮った絵を書けば、構図の模型をとばして
        # その骨格で縛って仕上げる。言葉だけの構図は、手の置き場所と腕の数を守らなかった（docs/knowledge/learning/illustration-composition.md）
        comp = os.environ.get("DRAW_COMPOSITION") or req.get("composition") or None
        t = time.time()
        seed = int(os.environ.get("DRAW_SEED") or req.get("seed", 7))   # 検品を通るまで、種を変えて描き直す（draw-one.yml）
        draw(req["prompt"], req["tags"], seed, req["compose"], req["render"], size=tuple(req.get("size", (832, 1216))),
             say=lambda m: print(m, flush=True), keep=out, composition=comp, variants=req.get("variants"), stage=stage)
        from chatdraw import handcheck
        checks = {}
        for f in sorted(out.glob("1-composition.png")) + sorted(out.glob("3-*.png")):
            res = handcheck.check(f)
            checks[f.name] = res
            print(f"{f.name}: {handcheck.summary(res)}", flush=True)
        if checks:
            (out / f"check-{stage}.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / f"request-{stage}.json").write_text(json.dumps(dict(req, seconds=round(time.time() - t)), ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
        print("exit=0")
        return
    if req.get("mode") == "logo":
        logo_candidates(req, out)
        print("exit=0")
        return
    from huggingface_hub import snapshot_download
    from chatdraw.models import image_model
    from chatdraw.paths import HUB
    m = image_model(req["repo"])
    t = time.time()
    snapshot_download(m.repo, cache_dir=str(HUB), **m.files)
    print(f"取った: {time.time() - t:.0f} 秒", flush=True)
    from chatdraw.engine import Painter
    p = Painter(m.repo, steps=req.get("steps", m.steps), size=tuple(req.get("size", (832, 1216))), guidance=req.get("guidance", m.guidance))
    t = time.time()
    im = p.paint(req["prompt"], req.get("seed", 7), on_step=lambda i, n: print(f"描いています {i}/{n}", flush=True))
    name = f"{m.repo.replace('/', '_')}-s{req.get('seed', 7)}.png"
    im.save(out / name)
    (out / "request.json").write_text(json.dumps(dict(req, seconds=round(time.time() - t), size_out=list(im.size)), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(f"描いた: {name} {im.size} {time.time() - t:.0f} 秒")
    print("exit=0")


def logo_candidates(req: dict, out: Path, painter=None):
    """ロゴの候補を種ごとに 1 枚ずつ描く（アプリのアイコンの候補など）。アプリの「ロゴ・マークを作る」と同じ chatdraw/logo.py の経路。
    頼みの形: {"mode": "logo", "repo": 模型, "name", "mood", "colors", "seeds": [..], "size": [w, h]}"""
    from chatdraw import logo
    if painter is None:
        from huggingface_hub import snapshot_download
        from chatdraw.engine import Painter
        from chatdraw.models import image_model
        from chatdraw.paths import HUB
        m = image_model(req["repo"])
        snapshot_download(m.repo, cache_dir=str(HUB), **m.files)
        painter = Painter(m.repo, steps=req.get("steps", m.steps), size=tuple(req.get("size", (1024, 1024))),
                          guidance=req.get("guidance", m.guidance))
    done = []
    if req.get("kind") == "icon":
        # アプリのアイコン: 意図・象徴・色の組を言葉にして描き、数字の検品を通った物だけを icon- で置く。落ちた物は fail- で残す
        # 色の組と象徴は palettes・symbols の列から種ごとに順に回す（1 回の実行で組を見比べられるように）
        pals = req.get("palettes") or [req.get("palette", "black-red-white")]
        syms = req.get("symbols") or [req.get("symbol", "head-nib")]
        for i, seed in enumerate(req.get("seeds", [7])):
            t = time.time()
            pal, sym = pals[i % len(pals)], syms[i % len(syms)]
            im, res, used, failed = logo.draw_icon(painter, pal, sym, seed,
                                                    req.get("tries", 3), size=tuple(req.get("size", (1024, 1024))),
                                                    say=lambda m: print(m, flush=True))
            name = f"{'icon' if res['ok'] else 'fail'}-{pal}-{sym}-s{used}.png"
            im.save(out / name)
            done.append(dict(file=name, seed=used, palette=pal, symbol=sym, prompt=logo.icon_prompt(pal, sym)[0], check=res, failed=failed, seconds=round(time.time() - t)))
            print(f"{name}: {'通った' if res['ok'] else '落ちた ' + '、'.join(res['faults'])} {time.time() - t:.0f} 秒", flush=True)
        (out / "request.json").write_text(json.dumps(dict(req, avoid=logo.ICON_AVOID, done=done), ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        return done
    for seed in req.get("seeds", [7]):
        t = time.time()
        mark = logo.draw_logo(painter, req.get("name", ""), req.get("mood", ""), req.get("colors", ""), seed,
                              size=tuple(req.get("size", (1024, 1024))), say=lambda m: print(m, flush=True))
        name = f"icon-s{seed}.png"
        logo.square(mark, 1024, 48).save(out / name)
        done.append(dict(file=name, seed=seed, seconds=round(time.time() - t)))
        print(f"描いた: {name} {time.time() - t:.0f} 秒", flush=True)
    prompt, avoid = logo.logo_prompt(req.get("name", ""), req.get("mood", ""), req.get("colors", ""))
    (out / "request.json").write_text(json.dumps(dict(req, prompt=prompt, avoid=avoid, done=done), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return done


if __name__ == "__main__":
    main()
