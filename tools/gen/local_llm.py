"""手元の言葉の模型（ローカル LLM）を、OpenAI 互換の窓口越しに使う部品。

Ollama・LM Studio・llama.cpp の server（llama-cpp-python の llama_cpp.server を含む）は、どれも
`/v1/chat/completions` を持つ。アプリは窓口の URL と模型の名前だけを知り、どの道具かは気にしない。

- CD_LLM_URL    窓口（既定 http://127.0.0.1:8081/v1。`tools/llm/setup.sh` で入れたものを app/start.sh がここで起こす）
- CD_LLM_MODEL  模型の名前（省略すると窓口の /models の先頭を使う。Ollama なら qwen2.5:7b のように渡す）
- CD_LLM_OFF=1  手元の模型を使わない（Claude か辞書で読む）

標準の部品（urllib）だけで書く。読み手の部品を足すと、描く処理の環境と画面のサーバーの両方に入れる必要が出るため。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8081/v1"


class LocalLLMError(RuntimeError):
    """窓口につながらない、答えが決めた形になっていない、など。呼ぶ側は次の読み手（Claude か辞書）へ回す。"""


class LocalLLM:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 180.0):
        self.url = (url or os.environ.get("CD_LLM_URL") or DEFAULT_URL).rstrip("/")
        self.model = model or os.environ.get("CD_LLM_MODEL") or None
        # CPU の小さい模型でも、数百字の答えは 1 分以内に返る。初回は模型の読み込みが重なるので長めに待つ
        self.timeout = timeout

    def _req(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            raise LocalLLMError(f"{self.url}{path}: {e}") from e

    def models(self) -> list[str]:
        return [m["id"] for m in self._req("/models", timeout=5).get("data", [])]

    def status(self) -> dict:
        """画面に出す状態。つながらなくても例外にせず、理由を返す。"""
        try:
            names = self.models()
        except LocalLLMError as e:
            return {"ok": False, "url": self.url, "error": str(e)}
        return {"ok": bool(names), "url": self.url, "model": self.model or (names[0] if names else None), "models": names}

    def chat_json(self, system: str, user: str, schema: dict, max_tokens: int = 800) -> dict:
        """決めた JSON の形（schema）で答えさせる。形に合わなければ LocalLLMError。
        温度は 0。同じ頼みごとには同じ答えを返させる（描き直しのたびに読み方が変わると、直したい所が追えない）"""
        model = self.model or (self.models() or [None])[0]
        if not model:
            raise LocalLLMError(f"{self.url}: 模型が1つも読まれていない")
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": True}},
        }
        r = self._req("/chat/completions", body)
        try:
            text = r["choices"][0]["message"]["content"]
            got = json.loads(_strip_fence(text))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise LocalLLMError(f"答えが JSON になっていない: {str(r)[:200]}") from e
        missing = [k for k in schema.get("required", []) if k not in got]
        if missing:
            raise LocalLLMError(f"答えに {missing} が無い")
        return got


def _strip_fence(text: str) -> str:
    """窓口によっては json_schema を無視して ```json で囲んで返す。囲みだけ外す。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def client() -> LocalLLM | None:
    """使ってよいときだけ返す。CD_LLM_OFF=1 なら使わない。つながるかどうかは呼ぶ側が試す（落ちたら次の読み手へ）。"""
    if os.environ.get("CD_LLM_OFF") == "1":
        return None
    return LocalLLM()
