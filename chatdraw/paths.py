"""置き場所を 1 か所で決める。

自作の AdaptiveAIStudio と同じ形にそろえる。
- アプリ本体: C:\\Program Files\\CharacterDesigner（インストーラが置く。書き換えない）
- 模型と記録: C:\\ProgramData\\CharacterDesigner（書き換える）
ProgramData に置くのは、利用者名が全角だと AppData の道に全角が入り、llama.cpp が模型を開けないため。

言葉の模型（GGUF）は AdaptiveAIStudio と同じ物を使い回す。AdaptiveAIStudio の置き場
（C:\\ProgramData\\AdaptiveAIStudio\\models）があればそこを読み、新しく取る物もそこへ置く。
同じ数 GB を 2 か所に持たないため。どちらのアプリも、相手の物を消さない。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def program_data() -> Path | None:
    if sys.platform != "win32":
        return None
    return Path(os.environ.get("ProgramData") or "C:\\ProgramData")


def data_home() -> Path:
    """模型と記録の根。CD_HOME > Windows の ProgramData > 開発中の .cache の順に決める"""
    if os.environ.get("CD_HOME"):
        return Path(os.environ["CD_HOME"])
    pd = program_data()
    if pd is not None:
        return pd / "CharacterDesigner"
    return ROOT / ".cache"


HOME = data_home()
HUB = HOME / "gen" / "hf" / "hub"     # 絵の模型（Hugging Face の形のまま）
OWN_LLM = HOME / "llm"                 # 言葉の模型を動かす部品と、AdaptiveAIStudio が無いときの置き場


def shared_llm_dir() -> Path | None:
    """AdaptiveAIStudio の模型の置き場。AAS_HOME があればそれを、無ければ ProgramData の既定を見る"""
    if os.environ.get("AAS_HOME"):
        d = Path(os.environ["AAS_HOME"]) / "models"
    else:
        pd = program_data()
        d = pd / "AdaptiveAIStudio" / "models" if pd is not None else Path.home() / ".aas" / "models"
    return d if d.is_dir() else None


def llm_dirs() -> list[Path]:
    """言葉の模型を探す場所。共有の置き場を先に見る"""
    return [d for d in (shared_llm_dir(), OWN_LLM) if d is not None]


def llm_target() -> Path:
    """新しく取る言葉の模型の置き場"""
    return shared_llm_dir() or OWN_LLM


def find_gguf(name: str) -> Path | None:
    for d in llm_dirs():
        p = d / name
        if p.is_file():
            return p
    return None
