"""言葉の模型を取る部品（chatdraw/fetchfile.py）: 切れたら続きから取り直す、決めた回数で止める、404 は取り直さない、GGUF でない物は置かない"""
import http.server
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chatdraw.fetchfile import Resumable, fetch_resumable  # noqa: E402

SIZE = 1 << 20
BODY = b"GGUF" + bytes(SIZE - 4)


def serve(plan, body=BODY):
    """plan(回) が 'ok'・'cut'（半分で切る）・'busy'（503）・'gone'（404）を返す配り元"""
    asked = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            asked.append(self.headers.get("Range"))
            how = plan(len(asked))
            if how == "busy":
                self.send_response(503); self.end_headers(); return
            if how == "gone":
                self.send_response(404); self.end_headers(); return
            start = int((self.headers.get("Range") or "bytes=0-")[6:-1] or 0)
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            if how == "cut":
                self.wfile.write(body[start:start + (len(body) - start) // 2])
                self.wfile.flush()
                self.connection.close()
                return
            self.wfile.write(body[start:])

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/m.gguf", asked, srv


class FetchTest(unittest.TestCase):
    def test_cut_then_resumes_by_itself(self):
        url, asked, srv = serve(lambda n: "cut" if n == 1 else "ok")
        waits, notes = [], []
        with TemporaryDirectory() as d:
            dest = Path(d) / "m.gguf"
            fetch_resumable(url, dest, len(BODY), sleep=waits.append, note=notes.append)
            self.assertEqual(dest.read_bytes(), BODY)
            self.assertFalse(dest.with_suffix(".part").exists())
        srv.shutdown()
        self.assertEqual(waits, [2])
        self.assertTrue(asked[-1] and asked[-1].startswith("bytes="), asked)   # 続きから求めた
        self.assertIn("続きから取り直します（1/3）", notes[0])

    def test_gives_up_after_retries(self):
        url, asked, srv = serve(lambda n: "busy")
        waits = []
        with TemporaryDirectory() as d:
            with self.assertRaises(Resumable):
                fetch_resumable(url, Path(d) / "m.gguf", len(BODY), sleep=waits.append)
        srv.shutdown()
        self.assertEqual(waits, [2, 4, 8])
        self.assertEqual(len(asked), 4)

    def test_404_is_not_retried(self):
        url, asked, srv = serve(lambda n: "gone")
        with TemporaryDirectory() as d:
            with self.assertRaises(urllib.error.HTTPError):
                fetch_resumable(url, Path(d) / "m.gguf", len(BODY), sleep=lambda s: None)
        srv.shutdown()
        self.assertEqual(len(asked), 1)

    def test_not_gguf_is_not_placed(self):
        url, _, srv = serve(lambda n: "ok", body=b"<html>" + bytes(100))
        with TemporaryDirectory() as d:
            dest = Path(d) / "m.gguf"
            with self.assertRaises(ValueError):
                fetch_resumable(url, dest, 0, sleep=lambda s: None)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_suffix(".part").exists())
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
