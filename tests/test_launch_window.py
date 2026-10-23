"""起動役（app/launch.py）が、ブラウザーではなくアプリのウィンドウで画面を開くことを、偽の pywebview で確かめる"""
import importlib.util
import subprocess
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("cd_launch", ROOT / "app" / "launch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class LaunchWindow(unittest.TestCase):
    def test_launch_does_not_use_webbrowser(self):
        self.assertNotIn("webbrowser", (ROOT / "app" / "launch.py").read_text(encoding="utf-8"))

    def test_open_window_uses_pywebview(self):
        calls = {}
        fake = types.ModuleType("webview")
        fake.create_window = lambda title, url, **kw: calls.update(title=title, url=url, kw=kw)
        fake.start = lambda: calls.update(started=True)
        sys.modules["webview"] = fake
        try:
            self.assertTrue(load().open_window("http://127.0.0.1:8000/"))
        finally:
            del sys.modules["webview"]
        self.assertEqual(calls["title"], "CharacterDesigner")
        self.assertEqual(calls["url"], "http://127.0.0.1:8000/")
        self.assertTrue(calls["started"])

    def test_open_window_without_pywebview_returns_false(self):
        sys.modules["webview"] = None  # import を失敗させる
        try:
            self.assertFalse(load().open_window("http://127.0.0.1:8000/"))
        finally:
            del sys.modules["webview"]

    def test_wait_ready_returns_when_server_answers(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"[]")

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(load().wait_ready(f"http://127.0.0.1:{srv.server_port}/", tries=5))
        finally:
            srv.shutdown()

    def test_help_shows_no_window_and_hides_old_name(self):
        out = subprocess.run([sys.executable, "app/launch.py", "--help"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertIn("--no-window", out)
        self.assertNotIn("--no-browser", out)


if __name__ == "__main__":
    unittest.main()
