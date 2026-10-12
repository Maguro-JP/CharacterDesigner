"""Claude から手元のアプリを使うための MCP サーバー（docs/app/PLAN.md の M5）。

中身は持たず、手元のアプリのサーバー（app/server、既定 http://127.0.0.1:8000）を呼ぶだけにする。
描く処理を二重に持たないため（モデルの読み込みも1か所で済む）。先に `sh app/start.sh` でアプリを起動しておく。

起動（Claude Desktop / Claude Code から stdio で呼ぶ）:
  PYTHONPATH=.cache/app/lib python3 -m app.mcp.server
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API = os.environ.get("CD_API", "http://127.0.0.1:8000").rstrip("/")

mcp = MCPServer(
    name="characterdesigner",
    instructions=(
        "亜人（獣耳・尾・翼・角のあるキャラクター）の設定資料を、手元のアプリで描いて検品する。"
        "流れ: describe で日本語の頼みごとを種の設定に組む → save_case で保存 → draw で描く依頼 → "
        "job で進み具合を見る（1回 約3分、最初の1件はモデルの読み込みに 約10分）→ sheet で通った絵を受け取る。"
    ),
)


def _call(method: str, path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        # アプリは理由を detail に日本語で返す。そのまま Claude に渡す
        detail = json.loads(e.read() or b"{}").get("detail", e.reason)
        raise ToolError(f"アプリが断った（{e.code}）: {detail}") from None
    except urllib.error.URLError as e:
        raise ToolError(f"アプリに繋がらない（{API}）。先に sh app/start.sh で起動する: {e.reason}") from None


def _json(method: str, path: str, body: dict | None = None):
    return json.loads(_call(method, path, body))


@mcp.tool()
def list_cases() -> dict:
    """描ける種（亜人の設定）の一覧。名前と表示名、部品を返す。"""
    return {name: {"ja": c.get("ja"), "parts": c.get("parts"), "kind": c.get("kind")} for name, c in _json("GET", "/api/cases").items()}


@mcp.tool()
def describe(text: str) -> dict:
    """日本語の頼みごと（例: 白い狐の巫女）を種の設定に組む。保存はしない。使わなかった言葉と注意も返す。"""
    return _json("POST", "/api/describe", {"text": text})


@mcp.tool()
def save_case(name: str, case: dict) -> dict:
    """種の設定を保存する（describe で組んだ case をそのまま渡せる）。name は英小文字・数字・- _。"""
    return _json("PUT", f"/api/cases/{name}", case)


@mcp.tool()
def draw(case: str, tries: int = 3) -> dict:
    """種を描く依頼を出す。すぐ仕事の id を返す。描き終わるまでは job で見る。"""
    j = _json("POST", "/api/jobs", {"case": case, "tries": tries})
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def job(id: str) -> dict:
    """仕事の進み具合と、回ごとの検品で落ちた部品を返す。state が done で passed が true なら sheet で絵を受け取れる。"""
    j = _json("GET", f"/api/jobs/{id}")
    lost = [{"try": r["try"] + 1, "lost": [f"{x['view']} {x['part']}" for x in r.get("result") or [] if not x["ok"]]}
            for r in j["results"] if r.get("result") is not None]
    return {"state": j["state"], "try": None if j["try_index"] is None else j["try_index"] + 1, "tries": j["tries"],
            "passed": j["passed"], "error": j["error"], "checks": lost}


@mcp.tool()
def sheet(id: str) -> Image:
    """検品を通った設定資料（4方向の1枚）を画像で返す。"""
    return Image(data=_call("GET", f"/api/jobs/{id}/files/sheet.png"), format="png")


@mcp.tool()
def studio_draw(text: str = "", prompt: str = "", size: str = "portrait", tries: int = 3, ref: str = "", ref_scale: float = 0.5) -> dict:
    """スタジオに頼む。日本語の頼みごと（text）か、英語の描く言葉（prompt）のどちらかを渡す。
    7つの役割（安全・読み手・演出・描き手・検品・意地の悪い目・整理）が順に回し、検品で落ちたら直して描き直す。
    size は portrait・landscape・square。ref は ref_save で手元に置いた参考画像の id で、画風と色の手本にする（強さ ref_scale、0〜1）。
    すぐ仕事の id を返す。進みは studio_job、絵は studio_image で受け取る。"""
    body = {"text": text, "prompt": prompt, "size": size, "tries": tries}
    if ref:
        body.update(ref=ref, ref_scale=ref_scale)
    j = _json("POST", "/api/studio/jobs", body)
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def studio_job(id: str) -> dict:
    """スタジオの仕事の進みと決着。events は役割ごとの出来事（誰が・何を）。passed が true なら studio_image で絵を受け取れる。"""
    j = _json("GET", f"/api/jobs/{id}")
    oc = j.get("outcome") or {}
    return {"state": j["state"], "passed": j["passed"], "error": j["error"],
            "events": [f"{e['role']}: {e['msg']}" for e in j.get("events") or []],
            "prompt": oc.get("prompt"), "reason": oc.get("reason"), "critique": oc.get("critique"), "files": oc.get("files")}


@mcp.tool()
def studio_image(id: str, file: str = "") -> Image:
    """スタジオの仕事の絵を返す。file を省くと検品を通った絵（無ければ最後に描いた絵）。"""
    j = _json("GET", f"/api/jobs/{id}")
    oc = j.get("outcome") or {}
    name = file or oc.get("passed") or (oc.get("files") or [None])[-1]
    if not name:
        raise ToolError("まだ絵が無い。studio_job で state が done になるまで待つ")
    return Image(data=_call("GET", f"/api/jobs/{id}/files/{name}"), format="png")


@mcp.tool()
def turnaround(character: str, count: int = 1, seed: int = 0) -> dict:
    """設定資料集のキャラクターの三面図（正面・横・後ろ）を描く。人形の下絵を3方向から写し、向きごとに count 枚描く。
    CPU で1枚 数分かかる。すぐ仕事の id を返す。進みは turnaround_job、絵は turnaround_image で受け取る。検品はしない"""
    j = _json("POST", f"/api/bible/{character}/turnaround", {"count": count, "seed": seed})
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def turnaround_job(id: str) -> dict:
    """三面図の仕事の進み。files は描けた絵の名前（front-0.png・side-0.png・back-0.png のように向きが頭に付く）"""
    j = _json("GET", f"/api/jobs/{id}")
    return {"state": j["state"], "error": j["error"], "files": j.get("files") or []}


@mcp.tool()
def turnaround_image(id: str, file: str) -> Image:
    """三面図の仕事の絵を1枚返す。file は turnaround_job の files の名前"""
    return Image(data=_call("GET", f"/api/jobs/{id}/files/{file}"), format="png")


@mcp.tool()
def proposals() -> dict:
    """待機中にスタジオが拾った提案（描き直し・見本の無い種など）。描くかは do_proposal で決める。"""
    return _json("GET", "/api/proposals")


@mcp.tool()
def do_proposal(id: str) -> dict:
    """提案を承認して描く。仕事の id を返す。"""
    j = _json("POST", f"/api/proposals/{id}/do")
    return {"id": j["id"], "kind": j.get("kind"), "state": j["state"]}


@mcp.tool()
def ref_search(query: str, n: int = 12, commercial: bool = False) -> dict:
    """参考画像を探す（CC ライセンスと public domain の画像、Openverse）。英語の言葉が多く当たる。
    返す各件に作者・ライセンス・元のページがある。使う条件はそれで確かめる。commercial=True で営利で使えるものだけ。
    描くときに使うなら、選んだ1件をそのまま ref_save に渡す。"""
    from urllib.parse import urlencode
    return _json("GET", "/api/refs/search?" + urlencode({"q": query, "n": n, "commercial": str(commercial).lower()}))


@mcp.tool()
def ref_save(item: dict) -> dict:
    """ref_search の結果の1件を手元に置く（.cache/app/refs。リポジトリには入れない）。返す id を studio_draw の ref に渡す。"""
    return _json("POST", "/api/refs", item)


@mcp.tool()
def ref_list() -> dict:
    """手元に置いた参考画像の一覧（id・作者・ライセンス・元のページ）。"""
    return _json("GET", "/api/refs")


if __name__ == "__main__":
    mcp.run()
