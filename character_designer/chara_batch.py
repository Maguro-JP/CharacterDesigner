"""キャラクターの一括生成: .chara の組から、三面図と表情差分をまとめて描く。

頼みの一覧から絵を描く一括生成（atelier/ai/batch.py）とは別の物で、人物ごとに設定資料へ描き足して .chara に戻す。
本体の側に置くと本体がキャラクターデザインを読むことになるので、キャラクターデザインの側に置く。
"""
from __future__ import annotations


def chara_jobs(paths) -> list[dict]:
    """キャラクターの一覧（.chara の組）を、まとめて描く物の並びにする。読めないファイルは理由を付けて返す"""
    from character_designer import chara_file as charafile
    out = []
    for p in paths:
        try:
            ch = charafile.load(p)
            out.append({"path": str(p), "name": ch["manifest"]["name"], "chara": ch})
        except charafile.BadFile as e:
            out.append({"path": str(p), "name": str(p), "error": str(e)})
    return out


def run_charas(jobs: list[dict], painter, seed: int = 0, what=("turnaround", "expressions"), say=lambda m: None,
               stopped=lambda: False, home=None, size=None) -> dict:
    """キャラクターごとに三面図と表情差分（what）を描き、.chara に足す。1 人が失敗しても残りを描き続ける"""
    from character_designer import chara_design as charadesign
    from character_designer import chara_file as charafile
    from atelier.ai.engine import Stopped
    out = {"done": [], "failed": [], "stopped": False, "total": len(jobs)}
    for k, j in enumerate(jobs, 1):
        if stopped():
            out["stopped"] = True
            break
        if j.get("error"):
            out["failed"].append((k, j["name"], j["error"]))
            continue
        try:
            ident = charafile.to_bible(j["chara"], home)
            for key in what:
                say(f"一括生成 {k}/{len(jobs)}: {j['name']}の{dict((e[0], e[1]) for e in charadesign.EXTRAS)[key]}")
                charadesign.run_extra(key, painter, ident, seed + k, say=say, home=home, size=size)
            charadesign.sync_chara(ident, j["path"], home)
            out["done"].append(j["path"])
        except Stopped:
            out["stopped"] = True
            break
        except Exception as e:   # noqa: BLE001  1 人の失敗で残りを止めない
            from atelier.ai.engine import explain
            out["failed"].append((k, j["name"], explain(e)))
    return out
