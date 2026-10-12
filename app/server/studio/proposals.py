"""待機中の提案（手本: Maguro-JP/AdaptiveAIStudio の docs/INITIATIVE.md・IDLE.md）。

手がかりは機械で拾う（模型を使わない。事実の収集は機械の方が速く確かで無料）。拾うのは確かめられる事実だけ:
- スタジオで通らなかった頼みごと（seed を変えて描き直せば通るかもしれない）
- 通ったが、意地の悪い目（CRITIC）が弱さを指摘した絵（光を絞って描き直す）
- 設定資料集のキャラクターのうち、三面図をまだ描いていないもの（まだ描いていない向き）
- 亜人の種のうち、見本（library/samples/demi3d-<種>.png）がまだ無いもの

提案は積むだけで、描かない。CPU で1枚 数分かかるので、描くかは利用者が決める。
役に立たない提案が並ぶと読まれなくなるので、出すのは上から MAX 件まで。退けたものは二度と出さない。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MAX = 5


def _id(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:10]


def gather(jobs: list, cases: dict, samples: Path, characters: list | tuple = ()) -> list[dict]:
    """手がかりから提案を作る。新しいものが先。頼みは /api/studio/jobs か /api/jobs にそのまま渡せる形で持つ"""
    out = []
    for j in sorted(jobs, key=lambda j: -j.created):
        if j.kind != "studio" or j.state != "done" or not j.free:
            continue
        spec, oc = j.free, j.outcome or {}
        size = {(832, 1216): "portrait", (1216, 832): "landscape", (1024, 1024): "square"}.get((spec["width"], spec["height"]), "portrait")
        base = {"text": spec.get("text", ""), "prompt": oc.get("prompt") or spec.get("prompt", ""), "negative": oc.get("negative", ""),
                "size": size, "tries": spec.get("tries", 3), "direct": False}
        title = spec.get("text") or spec.get("prompt", "")[:30]
        if not j.passed:
            out.append({"id": _id("retry", j.id), "kind": "studio", "title": f"「{title}」を seed を変えて描き直す",
                        "why": oc.get("reason") or "通らなかった", "who": "INSPECTOR",
                        "request": {**base, "seed": spec.get("seed", 0) + spec.get("tries", 3)}})
        elif oc.get("critique"):
            prompt = base["prompt"]
            if "single light source" not in prompt:
                prompt += ", single light source"
            if "dramatic lighting" not in prompt:
                prompt += ", dramatic lighting, strong contrast"
            # seed も進める。描く言葉も seed も同じだと、まったく同じ絵が出た（提案が役に立たなかった）
            out.append({"id": _id("relight", j.id), "kind": "studio", "title": f"「{title}」を光を強く絞って描き直す",
                        "why": "、".join(oc["critique"]), "who": "CRITIC",
                        "request": {**base, "prompt": prompt, "seed": spec.get("seed", 0) + spec.get("tries", 3)}})
    # 既に頼んだのと同じ描き方（描く言葉と seed）は提案しない。描き直しの描き直しを延々と積まないため
    asked = {(j.free.get("prompt", ""), j.free.get("seed")) for j in jobs if j.kind == "studio" and j.free}
    out = [p for p in out if (p["request"]["prompt"], p["request"]["seed"]) not in asked]
    # 三面図は見本の提案より前に置く（見本の提案が上限の数だけあると、後ろに置いた提案は並ばなかった）
    turned = {j.free.get("character") for j in jobs if j.kind == "turnaround" and j.free}
    for c in characters:
        if c["id"] not in turned:
            out.append({"id": _id("turnaround", c["id"]), "kind": "turnaround", "title": f"{c['name']}の三面図を描く",
                        "why": "正面・横・後ろをまだ描いていない", "who": "CURATOR",
                        "request": {"character": c["id"], "count": 1, "seed": 0}})
    for name, c in cases.items():
        if not (samples / f"demi3d-{name}.png").exists():
            out.append({"id": _id("sample", name), "kind": "demi", "title": f"{c.get('ja', name)}の設定資料を描いて見本にする",
                        "why": "見本がまだ無い", "who": "CURATOR", "request": {"case": name, "tries": 3}})
    return out


class Store:
    """退けた提案を覚える（同じ提案を何度も出さない）。"""

    def __init__(self, path: Path):
        self.path = path

    def dismissed(self) -> set:
        try:
            return set(json.loads(self.path.read_text()).get("dismissed", []))
        except (OSError, ValueError):
            return set()

    def dismiss(self, pid: str) -> None:
        d = self.dismissed() | {pid}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"dismissed": sorted(d)}))

    def visible(self, items: list) -> list:
        gone = self.dismissed()
        return [p for p in items if p["id"] not in gone][:MAX]
