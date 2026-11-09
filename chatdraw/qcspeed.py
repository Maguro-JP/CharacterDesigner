"""1 枚を描いて直すまでの時間を、工程ごとの秒で測る（.github/workflows/qcspeed.yml が版ごとに流す）。

検品と直しに上限を置かない形にしてから、1 枚に何十倍も時間がかかった。どの工程が何秒で、描き直しが何回、
何の崩れが理由だったかを数えないと、重い所から直せないので、Studio.draw の中の工程をそのまま包んで測る。
測る版のコード（PYTHONPATH の chatdraw）を書き換えずに、関数を包むだけにする（前の版にも同じ物差しを当てるため）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

t0 = time.perf_counter()

# 工程の名前 → (模型の置き場, 関数の名前)
STAGES = {
    "描く": ("chatdraw.engine", "Painter.paint"),
    "直し": ("chatdraw.engine", "Painter.redraw"),
    "handcheck": ("chatdraw.handcheck", "check"),
    "origqc": ("chatdraw.origqc", "check"),
    "requestcheck": ("chatdraw.requestcheck", "check"),
    "sanity": ("chatdraw.sanity", "check"),
    "director.slack": ("chatdraw.director", "slack"),
    "director.final_check": ("chatdraw.director", "final_check"),
}


def reason_kind(bad: str) -> str:
    """崩れの言葉を、数える種類にまとめる（「検品できなかった」は部品が無い・読めない物）"""
    s = str(bad)
    if s.startswith("検品できなかった"):
        return "検品できなかった"
    return s.split(":")[0].split("（")[0].strip()[:24] or "?"


def wrap(times: dict, counts: dict):
    """STAGES の関数を包み、呼ばれた回数と秒を足していく。無い版の工程は飛ばす"""
    import importlib
    for name, (mod, attr) in STAGES.items():
        try:
            m = importlib.import_module(mod)
        except Exception:   # noqa: BLE001  その版に無い工程
            continue
        owner, fn = m, attr
        if "." in attr:
            cls, fn = attr.split(".")
            owner = getattr(m, cls, None)
        f = getattr(owner, fn, None) if owner is not None else None
        if f is None:
            continue

        def make(f, name):
            def timed(*a, **k):
                t = time.perf_counter()
                try:
                    return f(*a, **k)
                finally:
                    times[name] = times.get(name, 0.0) + time.perf_counter() - t
                    counts[name] = counts.get(name, 0) + 1
            return timed
        setattr(owner, fn, make(f, name))


def run(out: Path, label: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    times, counts = {}, {}
    wrap(times, counts)
    rounds = []   # 描き直し・直しの回ごとの崩れ（止めて保存まで行かなくても残す）
    try:
        from chatdraw import persist
        go = persist.Persist.go_on

        def logged(self, bad):
            r = go(self, bad)
            rounds.append({"t": round(time.perf_counter() - t0, 1), "hands": len(self.hands), "bad": [str(b) for b in (bad or [])],
                           "go_on": r, "reason": self.reason})
            (out / f"rounds-{label}.json").write_text(json.dumps(rounds, ensure_ascii=False, indent=1), encoding="utf-8")
            return r
        persist.Persist.go_on = logged
    except Exception:   # noqa: BLE001  その版に無い
        pass
    from chatdraw.engine import Painter, Studio
    import chatdraw.engine as _eng
    _cd = Painter._cpu_dtype
    def _cd_logged(self, info):
        d = _cd(self, info)
        print("cpu_dtype:", d, "bf16_fast:", _eng.bf16_fast(), "gb:", getattr(info, "gb", None), flush=True)
        result_dtype[0] = str(d)
        return d
    Painter._cpu_dtype = _cd_logged
    result_dtype = [None]
    model = os.environ.get("QC_MODEL", "cagliostrolab/animagine-xl-4.0")
    steps = int(os.environ.get("QC_STEPS", "12"))
    w, h = (int(x) for x in os.environ.get("QC_SIZE", "768x1024").split("x"))
    budget = float(os.environ.get("QC_BUDGET_MIN", "150")) * 60
    prompt = os.environ.get("QC_PROMPT", "1girl, solo, standing, full body, waving hand, school uniform, simple background")
    seed = int(os.environ.get("QC_SEED", "7"))
    painter = Painter(model, steps=steps, size=(w, h))
    studio = Studio(painter=painter, out=out / "img")
    global t0
    t0 = time.perf_counter()
    # 測る時間の上限を越えたら、止めるボタンと同じ印を立てる（打ち切られても、測れた分を書く）
    import threading
    threading.Timer(budget, lambda: setattr(painter, "stop", True)).start()

    def dump():   # 1 工程が数十分の遅い機械では止める印が効く前に打ち切られるので、測れた秒を 1 分ごとに書く
        while True:
            time.sleep(60)
            part = {"label": label, "partial": True, "elapsed_s": round(time.perf_counter() - t0, 1),
                    "stage_s": {k: round(v, 1) for k, v in times.items()}, "stage_calls": dict(counts)}
            (out / f"partial-{label}.json").write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
    threading.Thread(target=dump, daemon=True).start()
    result = {"label": label, "model": model, "steps": steps, "size": [w, h], "prompt": prompt, "seed": seed}
    try:
        _text, path = studio.draw(prompt, seed)
        result["image"] = str(path)
        meta = Path(path).with_suffix(".json")
        if meta.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            result["redraws"] = m.get("redraws", [])
            result["left"] = m.get("left", m.get("bad", []))
            result["fix_rounds"] = m.get("hand_rounds", [])
    except Exception as e:   # noqa: BLE001  止めた・落ちたときも、測れた秒は書く
        result["error"] = f"{type(e).__name__}: {e}"
    result["total_s"] = round(time.perf_counter() - t0, 1)
    result["stopped_by_budget"] = bool(getattr(painter, "stop", False))
    result["dtype"] = result_dtype[0]
    result["stage_s"] = {k: round(v, 1) for k, v in times.items()}
    result["stage_calls"] = counts
    rd = result.get("redraws") or []
    kinds: dict = {}
    for r in rd:
        for b in r.get("bad", []):
            kinds[reason_kind(b)] = kinds.get(reason_kind(b), 0) + 1
    result["redraw_n"] = max(0, len(rd) - 1)
    result["reasons"] = kinds
    result["bad_per_round"] = [len(r.get("bad", [])) for r in rd]
    result["rounds"] = rounds
    for r in rounds:
        for b in r["bad"]:
            kinds[reason_kind(b)] = kinds.get(reason_kind(b), 0) + 1
    (out / f"qcspeed-{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    os._exit(0) if result.get("stopped_by_budget") else None   # 止めた後の Timer の糸を待たない
    return result


if __name__ == "__main__":
    r = run(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "now")
    print(json.dumps({k: r[k] for k in ("label", "total_s", "redraw_n", "stage_s", "reasons", "bad_per_round") if k in r},
                     ensure_ascii=False))
    os._exit(0)
