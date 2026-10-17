"""描く仕事のモード。何を作るかで手順と、始める前にそろっていなければならないもの（門）を分ける。

  CharacterDesigner  人物を設計する。設定・目・表情・持ち物を書き、三面図と表情差分を描かせて checker が通す
  Illustrator        設計済みの人物（または人の参考資料）から、絵（イラスト）を描く
  Background         人物を描かずに、背景（場面）だけを作る
  Composite          人物を背景に描き入れる（貼るのは位置を決める下書きまで。完成は場面に合わせて描き直した絵）
  Ensemble           複数の人物を 1 枚に描き入れる（同じく、並べた絵は下書き）

AI が人物を描くときは、必ず CharacterDesigner から入る。設計を飛ばして言葉だけで描くと、描くたびに服・色・持ち物・顔が
変わり、手の崩れも多かった（人物 20 枚が 20 枚とも戻った、2026-10-17）。人が参考資料を付けて描くよう指示したときは、
人が設計を持っているので Illustrator からすぐ描いてよい。

  python3 tools/gen/modes.py list
  python3 tools/gen/modes.py plan <モード> [--character <id> ...] [--reference <画像>] [--world <id> --location <id>]
  python3 tools/gen/modes.py check <モード> [--character <id> ...] [--reference <画像>]   門を通れなければ終了コード 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402

G = "PYTHONPATH=.cache/gen/lib python3 tools/gen/"

MODES = {
    "CharacterDesigner": {
        "purpose": "人物を設計する（設定資料一式。8 区分は tools/gen/charsheet.py）",
        "steps": [
            ("1 基本情報: 名前・年齢・身長と頭身・役割・性格・背景設定を書く", "python3 tools/gen/bible.py new-character {c} ...（欄は bible/characters/{c}.json）"),
            ("4・5 目と表情、髪型を決める（表情担当 face-designer）", "python3 tools/gen/bible.py set-eyes {c} --tags ... / add-expression"),
            ("6 服の部位と持ち物・武装を決める（小物担当 prop-designer）", "python3 tools/gen/bible.py add-item {c} ..."),
            ("7・8 色見本（名前・値・部位）と、描くときの決まり・描いてはいけないものを書く", ""),
            ("2 全身の四面図（正面・背面・左・右）を描かせる", G + "bible.py turnaround {c} <出力>"),
            ("3 ポーズを 3 種以上描かせる（立ち・歩き・役どころの動作・持ち物を使う）", G + "bible.py draw {c} <出力> --pose ..."),
            ("4 胸から上の表情差分（8 種以上）と髪型差分（2 種以上）を描かせる", G + "bible.py expressions {c} <出力>"),
            ("5・6 目・髪・服の部位・持ち物の拡大を描かせる", G + "detail.py"),
            ("checker が 1 枚ずつ元の大きさで検品し、崩れた所だけを描き直させる", G + "fix.py / detail.py"),
            ("通した絵を役割の名前（view-front、pose-1、expr-smile、detail-eyes など）で登録する", "python3 tools/gen/bible.py add-image {c} <役割> <絵>"),
            ("資料を書き出して足りない区分を見る", "python3 tools/gen/charsheet.py render {c} <出力.html>"),
        ],
    },
    "Illustrator": {
        "purpose": "設計済みの人物、または人の参考資料から絵を描く",
        "steps": [
            ("門: 設計がそろっているか（人の参考資料があれば飛ばす）", "python3 tools/gen/bible.py design-status {c}"),
            ("描く", G + "bible.py draw {c} <出力> --scene ... [--reference <画像>]"),
            ("自動検品のあと、checker が元の大きさで検品する", G + "qc.py"),
        ],
    },
    "Background": {
        "purpose": "人物を描かずに背景だけを作る",
        "steps": [
            ("世界観と場所を書く（背景担当 background-artist）", "python3 tools/gen/bible.py new-world / add-location"),
            ("背景だけを描かせる（人が描かれていないかを検品）", G + "background.py draw {w} {l} <出力>"),
            ("checker が検品する", ""),
        ],
    },
    "Composite": {
        "purpose": "人物を背景に描き入れる（貼った絵は位置と大きさを決める下書き。完成は描き直した絵）",
        "steps": [
            ("人物の設計（三面図・色の手本）と背景を用意する", ""),
            ("下書き: 人物を背景に置いて、位置・大きさ・足元を決める（貼っただけの絵は完成にしない）", G + "layers.py <人物の絵> <出力> --bg <背景> --scene ..."),
            ("描き入れ: 下書きを土台に、キャラデザを参考画像として読ませ、場面の光と向きに合わせて絵全体を描き直させる",
             G + "bible.py draw {c} <出力> --base <下書き> --strength 0.55 --scene ..."),
            ("checker が、人物が背景の光・向き・大きさで描かれているか（貼った見た目でないか）と、設計どおりかを見る", ""),
        ],
    },
    "Ensemble": {
        "purpose": "複数の人物を 1 枚に組み合わせる",
        "steps": [
            ("門: 人物ごとに設計がそろっているか（人の参考資料があれば飛ばす）", "python3 tools/gen/bible.py design-status <id>"),
            ("人物ごとの絵（checker が通したもの）と背景を用意する", ""),
            ("下書き: 人物を並べて、重なり順と遠近の大きさを決める（貼っただけの絵は完成にしない）",
             G + "ensemble.py <出力> --bg <背景> --person <絵>:<x>:<高さ> --person ..."),
            ("描き入れ: 下書きを土台に、人物ごとのキャラデザを参考画像として読ませ、場面に合わせて絵全体を描き直させる", ""),
            ("重なり・大きさの釣り合い・視線・設計どおりかを checker が検品する", ""),
        ],
    },
}
# 人物の設計が要るモード（人の参考資料が無ければ、CharacterDesigner を先に終える）
NEEDS_DESIGN = {"Illustrator", "Ensemble"}


def check(mode: str, characters: list[str] | None = None, reference: str | None = None) -> dict:
    """モードを始めてよいか。ok が False なら、足りないもの（missing）を先にそろえる"""
    if mode not in MODES:
        raise SystemExit(f"モードが無い: {mode}（{', '.join(MODES)}）")
    missing = []
    if mode in NEEDS_DESIGN:
        if not characters and not reference:
            missing.append("描く人物（--character）か、人の参考資料（--reference）")
        for c in characters or []:
            try:
                bible.require_design(c, reference)
            except bible.DesignNotReady as e:
                missing.append(f"{c}: {e}")
        if mode == "Ensemble" and characters and len(characters) < 2 and not reference:
            missing.append("組み合わせる人物を 2 人以上")
    return {"mode": mode, "ok": not missing, "missing": missing,
            "via": "illustrator" if reference else ("design" if mode in NEEDS_DESIGN else None)}


def plan(mode: str, characters: list[str] | None = None, reference: str | None = None,
         world: str = "<world>", location: str = "<location>") -> dict:
    c = ",".join(characters or ["<id>"])
    steps = [{"step": s, "command": cmd.format(c=c, w=world, l=location)} for s, cmd in MODES[mode]["steps"]]
    return {"mode": mode, "purpose": MODES[mode]["purpose"], "check": check(mode, characters, reference), "steps": steps}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("plan", "check"):
        s = sub.add_parser(name)
        s.add_argument("mode", choices=list(MODES))
        s.add_argument("--character", action="append")
        s.add_argument("--reference")
        if name == "plan":
            s.add_argument("--world", default="<world>"); s.add_argument("--location", default="<location>")
    a = ap.parse_args()
    if a.cmd == "list":
        out = {m: v["purpose"] for m, v in MODES.items()}
    elif a.cmd == "plan":
        out = plan(a.mode, a.character, a.reference, a.world, a.location)
    else:
        out = check(a.mode, a.character, a.reference)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.cmd == "check" and not out["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
