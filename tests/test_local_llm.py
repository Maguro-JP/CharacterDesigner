"""手元の言葉の模型の窓口（tools/gen/local_llm.py）と、それで頼みごとを読む経路（demi_text.parse）の試験。
本物の模型は使わず、OpenAI 互換の偽の窓口を立てる。"""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 手元で画面から選んだ窓口（.cache/app/llm.json）を試験に持ち込まない
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ["CD_LLM_SETTINGS"] = os.path.join(tempfile.mkdtemp(), "llm.json")
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import demi_text  # noqa: E402
import local_llm  # noqa: E402


class FakeServer:
    """/v1/models と /v1/chat/completions だけを持つ偽の窓口。answer に返す本文を入れる。"""

    def __init__(self, answer):
        self.answer, self.requests = answer, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                b = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._send({"data": [{"id": "fake-model"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                content = outer.answer if isinstance(outer.answer, str) else json.dumps(outer.answer, ensure_ascii=False)
                self._send({"choices": [{"message": {"role": "assistant", "content": content}}]})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


WHITE_FOX = {"species": "fox", "species_color": "白", "hair_color": None, "eye_color": None,
             "hair_styles": [], "used": ["白い", "狐"], "unused": ["巫女"]}


class LocalLLMTest(unittest.TestCase):
    def test_reads_species_with_local_model(self):
        srv = FakeServer(WHITE_FOX)
        try:
            r = demi_text.parse("白い狐の巫女", local=local_llm.LocalLLM(srv.url))
        finally:
            srv.close()
        self.assertEqual(r["reader"], "local")
        self.assertEqual(r["name"], "white-fox")
        self.assertIn("white hair", r["case"]["hair"])
        # 答えの形（json_schema）と温度 0 を窓口に渡している
        req = srv.requests[0]
        self.assertEqual(req["model"], "fake-model")
        self.assertEqual(req["temperature"], 0)
        self.assertEqual(req["response_format"]["type"], "json_schema")

    def test_fenced_answer_is_accepted(self):
        srv = FakeServer("```json\n" + json.dumps(WHITE_FOX, ensure_ascii=False) + "\n```")
        try:
            r = demi_text.parse("白い狐", local=local_llm.LocalLLM(srv.url))
        finally:
            srv.close()
        self.assertEqual(r["reader"], "local")

    def test_unknown_species_falls_back_to_words(self):
        # 小さい模型が選択肢の外（dragon）を返したら、取り違えずに辞書で読み直す
        srv = FakeServer(dict(WHITE_FOX, species="dragon"))
        try:
            r = demi_text.parse("黒猫", local=local_llm.LocalLLM(srv.url))
        finally:
            srv.close()
        self.assertEqual(r["reader"], "words")
        self.assertEqual(r["name"], "black-cat")
        self.assertIn("手元の模型で読めなかった", r["notes"][0])

    def test_bad_color_is_dropped_not_fatal(self):
        srv = FakeServer(dict(WHITE_FOX, species_color="虹色"))
        try:
            r = demi_text.parse("狐", local=local_llm.LocalLLM(srv.url))
        finally:
            srv.close()
        self.assertEqual(r["reader"], "local")
        self.assertEqual(r["name"], "fox")

    def test_dictionary_corrects_small_model(self):
        # 0.5B の模型が「ピンクのうさぎ」を猫と読んだ。辞書の言葉に当たった種を使う
        srv = FakeServer(dict(WHITE_FOX, species="cat", species_color="ピンク"))
        try:
            r = demi_text.parse("ピンクのうさぎ、ポニーテール", local=local_llm.LocalLLM(srv.url))
        finally:
            srv.close()
        self.assertEqual(r["reader"], "local")
        self.assertEqual(r["name"], "pink-rabbit")
        self.assertIn("ponytail", r["case"]["hair"])
        self.assertTrue(any("辞書の言葉に当たった rabbit" in n for n in r["notes"]))

    def test_json_object_format_is_tried_next(self):
        # llama-cpp-python の窓口は json_schema を 500 で断り、json_object + schema なら受ける
        srv = FakeServer(WHITE_FOX)
        orig = srv.httpd.RequestHandlerClass.do_POST

        def picky(handler):
            n = int(handler.headers["Content-Length"])
            body = json.loads(handler.rfile.read(n))
            if body["response_format"]["type"] == "json_schema":
                handler.send_response(500)
                handler.end_headers()
                return
            srv.requests.append(body)
            handler._send({"choices": [{"message": {"content": json.dumps(WHITE_FOX, ensure_ascii=False)}}]})
        srv.httpd.RequestHandlerClass.do_POST = picky
        try:
            llm = local_llm.LocalLLM(srv.url)
            r = demi_text.parse("白い狐", local=llm)
        finally:
            srv.httpd.RequestHandlerClass.do_POST = orig
            srv.close()
        self.assertEqual(r["reader"], "local")
        self.assertEqual(llm._format, "json_object")
        self.assertEqual(srv.requests[0]["response_format"]["schema"]["required"][0], "species")

    def test_server_down_falls_back_quickly(self):
        r = demi_text.parse("黒猫", local=local_llm.LocalLLM("http://127.0.0.1:9/v1"))
        self.assertEqual(r["reader"], "words")
        self.assertEqual(r["name"], "black-cat")

    def test_status_reports_down_without_raising(self):
        s = local_llm.LocalLLM("http://127.0.0.1:9/v1").status()
        self.assertFalse(s["ok"])
        self.assertIn("error", s)

    def test_off_switch(self):
        import os
        old = os.environ.get("CD_LLM_OFF")
        os.environ["CD_LLM_OFF"] = "1"
        try:
            self.assertIsNone(local_llm.client())
        finally:
            if old is None:
                del os.environ["CD_LLM_OFF"]
            else:
                os.environ["CD_LLM_OFF"] = old


if __name__ == "__main__":
    unittest.main()
