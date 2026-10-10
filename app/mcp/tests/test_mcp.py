"""MCP サーバーを本物の MCP クライアントから stdio で起こし、偽の描き手のアプリに対して道具を通す。"""
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.server import main
from app.server.tests.test_api import FakeRunner

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    cases = tmp_path / "demi3d.json"
    shutil.copy(main.demi.CASES, cases)
    monkeypatch.setattr(main.demi, "CASES", cases)   # 保存の試験で本物の種の一覧を書き換えない
    monkeypatch.setattr(main, "DATA", tmp_path / "jobs")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    server = uvicorn.Server(uvicorn.Config(main.create_app(FakeRunner(pass_on=1)), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True); t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def run_tools(url, steps):
    async def go():
        env = {**os.environ, "CD_API": url, "PYTHONPATH": os.pathsep.join(sys.path)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"], env=env, cwd=str(ROOT))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
            await session.initialize()
            return await steps(session)
    return anyio.run(go)


def text(result):
    import json
    return json.loads(result.content[0].text)


def test_tools_end_to_end(app_url):
    async def steps(s):
        names = {t.name for t in (await s.list_tools()).tools}
        assert names == {"list_cases", "describe", "save_case", "draw", "job", "sheet"}
        assert "catgirl" in text(await s.call_tool("list_cases", {}))
        d = text(await s.call_tool("describe", {"text": "白い狐の巫女"}))
        assert d["name"] == "white-fox" and d["unused"] == ["巫女"]
        await s.call_tool("save_case", {"name": d["name"], "case": d["case"]})
        job = text(await s.call_tool("draw", {"case": "white-fox", "tries": 3}))
        for _ in range(100):
            st = text(await s.call_tool("job", {"id": job["id"]}))
            if st["state"] in ("done", "failed"):
                break
            await anyio.sleep(0.05)
        assert st["state"] == "done" and st["passed"] is True and st["try"] == 2
        assert st["checks"][0]["lost"] == ["back tail"]   # 1回目に落ちた部品
        img = await s.call_tool("sheet", {"id": job["id"]})
        assert img.content[0].type == "image" and img.content[0].mime_type == "image/png"
        bad = await s.call_tool("draw", {"case": "nope"})
        assert bad.is_error and "種「nope」は無い" in bad.content[0].text
    run_tools(app_url, steps)


def test_app_not_running_says_how_to_start():
    async def steps(s):
        r = await s.call_tool("list_cases", {})
        assert r.is_error and "sh app/start.sh" in r.content[0].text
    run_tools("http://127.0.0.1:9", steps)
