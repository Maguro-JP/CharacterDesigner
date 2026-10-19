"""guide が全部の道具を案内しているか。道具を足して guide に書き忘れると、Claude がその道具を見つけられない。"""
import json
import re
from pathlib import Path

from app.mcp import server

SRC = Path(server.__file__).read_text(encoding="utf-8")


def test_guide_names_every_tool():
    tools = re.findall(r"@mcp\.tool\(\)\s*\ndef (\w+)", SRC)
    text = json.dumps({"w": server.GUIDE, "v": server.DETAILS}, ensure_ascii=False)
    missing = [t for t in tools if t != "guide" and t not in text]
    assert len(tools) > 10
    assert missing == []
