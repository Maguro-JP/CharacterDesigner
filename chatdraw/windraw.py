"""利用者の Windows と同じ経路で、本物の模型を使って 1 枚描き、頼みが模型に伝わったかと出来を確かめる（Actions の Windows の機械で流す）。

    python -E -s -m chatdraw.windraw <出力の置き場> "<日本語の頼み>" [種]

Setup.exe で入れたアプリの Python で動かす。手元の Linux で通っても、利用者の Windows では動かないことがあったため、
描く確かめは Windows を本番にする。順は利用者が踏む順と同じにする。
1. 初回の取得（Fetcher.run）で、描く部品と絵の模型（Animagine XL 4.0）を取る
2. 検品の模型（手の模型、タグ読み）を取る
3. 日本語の頼みを、アプリと同じ経路（Words.to_prompt）で描く言葉に直し、何が模型に渡ったかを残す（prompt.json）
4. Studio.draw で描く（手の検品と直し、頼んだ物の検品、通らなければ種を変えて描き直す）
5. 描いた絵をもう一度タグ読みし、頼んだ物が描かれたか、手の崩れが残っているかを result.json に残す
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

MODEL = "cagliostrolab/animagine-xl-4.0"


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "windraw-out")
    text = sys.argv[2] if len(sys.argv) > 2 else "白いビキニの女性が海で手を振っている 全身"
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7   # Actions では種を変えて何本も同時に描く
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report: dict = {"request": text, "steps": []}

    def step(name, fn):
        t = time.time()
        try:
            detail = fn()
            report["steps"].append({"name": name, "ok": True, "seconds": round(time.time() - t, 1), "detail": detail})
            print(f"OK   {name}（{time.time() - t:.0f} 秒）{json.dumps(detail, ensure_ascii=False) if detail else ''}", flush=True)
            return True
        except Exception:
            report["steps"].append({"name": name, "ok": False, "seconds": round(time.time() - t, 1), "error": traceback.format_exc()[-3000:]})
            print(f"FAIL {name}\n{traceback.format_exc()[-3000:]}", flush=True)
            return False

    import chatdraw.app  # noqa: F401  起動と同じ順に読む（出力の付け替え、環境の切り離し、部品の置き場）
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from chatdraw.models import image_model
    state: dict = {}

    def fetch():
        from chatdraw.setup import Fetcher
        f = Fetcher()
        said, done = [], []
        f.progress.connect(lambda msg, pct: said.append(msg))
        f.finished.connect(lambda err: done.append(err))
        f.run(image_model(MODEL), None)
        if done and done[0]:
            raise RuntimeError(done[0])
        return {"messages": said[-3:]}

    def checkers():
        from chatdraw import handcheck, requestcheck
        handcheck.ensure_models(True)
        requestcheck._tagger(True)
        from chatdraw.engine import bf16_fast, total_ram_gb
        return {"bf16_fast": bf16_fast(), "ram_gb": round(total_ram_gb())}

    def convey():
        from chatdraw.engine import Words
        w = Words(Path(""))   # 言葉の模型を入れていない利用者と同じ（語の表で直す）
        tags = w.to_prompt(text, tags=True)
        from chatdraw.jaterms import leftover
        lost = leftover(text)
        state["tags"] = tags
        (out / "prompt.json").write_text(json.dumps({"request": text, "tags": tags, "lost": lost}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        if tags == text:
            raise RuntimeError("日本語の頼みが、そのまま模型に渡っている（描く言葉に直っていない）")
        if lost:
            raise RuntimeError("模型に伝わらない言葉がある: " + "、".join(lost))
        return {"tags": tags}

    def draw():
        from chatdraw.engine import Painter, Studio, Words
        m = image_model(MODEL)
        studio = Studio(Words(Path("")), Painter(MODEL, steps=m.steps, guidance=m.guidance), out)
        studio.way = "one"
        said = []
        prompt, path = studio.draw(text, seed, on_status=lambda s: (said.append(s), print(s, flush=True)))
        state["path"], state["prompt"] = path, prompt
        return {"file": str(path), "prompt": prompt, "redraws": json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8")).get("redraws")}

    def judge():
        from chatdraw import handcheck, requestcheck
        hands = handcheck.check(state["path"])
        asked = requestcheck.check(state["path"], state["prompt"], fetch=True)
        res = {"hands": handcheck.summary(hands), "asked": requestcheck.summary(asked), "missing": asked.get("missing", []),
               "extra": asked.get("extra", []), "bad": hands["bad"],
               "passed": hands["readable"] and not hands["bad"] and not asked.get("missing") and not asked.get("extra")}
        (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        return res

    ok = step("描く部品と模型を取る", fetch)
    ok = ok and step("検品の模型を取る", checkers)
    ok = ok and step("頼みを描く言葉に直す（模型に何が渡るか）", convey)
    ok = ok and step("描く（検品と直しと描き直しを含む）", draw)
    ok = ok and step("出来を確かめる", judge)
    report["ok"] = ok
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"exit={0 if ok else 1}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
