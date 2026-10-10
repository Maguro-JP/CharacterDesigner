"""試験では手元の言葉の模型を使わない。手元で窓口が動いていると、読み手が変わって結果が揺れるため。
手元の模型の経路は test_local.py で偽の窓口を立てて試す。"""
import os

os.environ.setdefault("CD_LLM_OFF", "1")
