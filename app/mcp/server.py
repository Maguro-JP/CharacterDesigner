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
    lost = [{"try": r["try"] + 1, "lost": [f"{x['view']} {x['part']}" for x in r["result"] if not x["ok"]]} for r in j["results"]]
    return {"state": j["state"], "try": None if j["try_index"] is None else j["try_index"] + 1, "tries": j["tries"],
            "passed": j["passed"], "error": j["error"], "checks": lost}


@mcp.tool()
def sheet(id: str) -> Image:
    """検品を通った設定資料（4方向の1枚）を画像で返す。"""
    return Image(data=_call("GET", f"/api/jobs/{id}/files/sheet.png"), format="png")


if __name__ == "__main__":
    mcp.run()
