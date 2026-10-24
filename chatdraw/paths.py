"""置き場所を 1 か所で決める。

模型は数 GB あるので、自作のアプリどうしで共有する。共有の置き場は C:\\LLM（自作アプリ共通の決まり）。

    C:\\LLM\\
      README.txt      この置き場の説明（無ければ作る）
      gguf\\           言葉の模型（llama.cpp で読む .gguf）
      huggingface\\    絵の模型など、Hugging Face の形のままの模型

- 模型はまずここを探し、新しく取る物もここへ置く。同じ物を 2 か所に持たない
- 道は ASCII だけにする（利用者名が全角だと、AppData の道で llama.cpp が模型を開けなかった）
- どのアプリも、ほかのアプリが置いた模型を消さない。消すのは利用者が選んだときだけ
- LLM_HOME を書くと、共有の置き場をほかへ移せる

模型でない物（設定、描いた絵の記録、動かす部品）はアプリごとに C:\\ProgramData\\CharacterDesigner に置く。
アプリ本体は C:\\Program Files\\CharacterDesigner（インストーラーが置く。書き換えない）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"

README = """この置き場には、自作のアプリが共有して使う AI の模型が入っています。

gguf\\         言葉の模型（llama.cpp で読む .gguf）
huggingface\\  絵の模型など、Hugging Face の形のままの模型

複数のアプリが同じ模型を読みます。消すと、使っているアプリで取り直しになります。
置き場を移したいときは、環境変数 LLM_HOME に新しい場所を書いてください。
"""


def llm_home() -> Path:
    """共有の模型の置き場。LLM_HOME > Windows の C:\\LLM > 開発中の .cache の順に決める"""
    if os.environ.get("LLM_HOME"):
        return Path(os.environ["LLM_HOME"])
    if WINDOWS:
        return Path((os.environ.get("SystemDrive") or "C:") + "\\") / "LLM"
    return ROOT / ".cache"


def data_home() -> Path:
    """模型以外（設定・部品・記録）の置き場。CD_HOME > Windows の ProgramData > 開発中の .cache の順に決める"""
    if os.environ.get("CD_HOME"):
        return Path(os.environ["CD_HOME"])
    if WINDOWS:
        return Path(os.environ.get("ProgramData") or "C:\\ProgramData") / "CharacterDesigner"
    return ROOT / ".cache"


LLM_HOME = llm_home()
HOME = data_home()
# 開発中（Windows でない）は、これまでの置き場（.cache/gen/hf/hub と .cache/llm）をそのまま使う
HUB = LLM_HOME / "huggingface" if WINDOWS or os.environ.get("LLM_HOME") else LLM_HOME / "gen" / "hf" / "hub"
GGUF = LLM_HOME / "gguf" if WINDOWS or os.environ.get("LLM_HOME") else LLM_HOME / "llm"
OWN_LLM = HOME / "llm"   # 言葉の模型を動かす部品（llama-cpp-python）


def legacy_gguf_dirs() -> list[Path]:
    """共有の置き場を決める前に、模型が置かれていた所。読むだけで、ここへは取らない"""
    dirs = [OWN_LLM]
    if WINDOWS:
        dirs.append(Path(os.environ.get("ProgramData") or "C:\\ProgramData") / "AdaptiveAIStudio" / "models")
    if os.environ.get("AAS_HOME"):
        dirs.append(Path(os.environ["AAS_HOME"]) / "models")
    return dirs


def llm_dirs() -> list[Path]:
    """言葉の模型を探す場所。共有の置き場を先に見る"""
    out = []
    for d in [GGUF, *legacy_gguf_dirs()]:
        if d.is_dir() and d not in out:
            out.append(d)
    return out


def llm_target() -> Path:
    """新しく取る言葉の模型の置き場"""
    return GGUF


def find_gguf(name: str) -> Path | None:
    for d in llm_dirs():
        p = d / name
        if p.is_file():
            return p
    return None


def ensure_shared():
    """共有の置き場と説明を作る。既にある物は書き換えない"""
    for d in (HUB, GGUF):
        d.mkdir(parents=True, exist_ok=True)
    readme = LLM_HOME / "README.txt"
    if (WINDOWS or os.environ.get("LLM_HOME")) and not readme.exists():
        readme.write_text(README, encoding="utf-8")
