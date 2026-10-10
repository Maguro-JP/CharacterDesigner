"""試験では手元の言葉の模型を使わない。手元で窓口が動いていると、読み手が変わって結果が揺れるため。
手元の模型の経路は test_local.py で偽の窓口を立てて試す。"""
import os

os.environ.setdefault("CD_LLM_OFF", "1")

# 画面で選んだ窓口の設定も、手元の .cache/app/llm.json を読まない（試験ごとの一時フォルダに向ける）
import tempfile  # noqa: E402

os.environ.setdefault("CD_LLM_SETTINGS", os.path.join(tempfile.mkdtemp(), "llm.json"))
# 覚えていること・画面の配置も、手元のもの（.cache/app）に試験から書き込まない
_tmp = tempfile.mkdtemp()
os.environ.setdefault("CD_MEMORY", os.path.join(_tmp, "memory.jsonl"))
os.environ.setdefault("CD_LAYOUT", os.path.join(_tmp, "layout.json"))
os.environ.setdefault("CD_PROPOSALS", os.path.join(_tmp, "proposals.json"))
