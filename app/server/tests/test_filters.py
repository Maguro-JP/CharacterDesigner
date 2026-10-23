"""描く前の判定: 子どもを性的に描くことだけを止める固定の制限。ほかは止めない（利用者のフィルターは外した）"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import free_text  # noqa: E402

from app.server.tests.test_api import FakeRunner, client  # noqa: E402,F401


def test_only_the_fixed_limit_blocks(client):  # noqa: F811
    c, _ = client(FakeRunner())
    assert c.get("/api/filters").status_code == 404
    assert free_text.blocked_text("bloody knight") is None
    assert "固定の制限" in free_text.blocked_text("child, nude")
    assert free_text.blocked_text("adult woman, nude") is None
