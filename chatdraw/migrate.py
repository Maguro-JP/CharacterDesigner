"""前の版（%LOCALAPPDATA%\\Programs\\CharacterDesigner に入れた版）から、新しい置き場へ移す。インストーラーが 1 回だけ呼ぶ。

前の版は、プログラムも模型も描いた物も、入れた場所 1 か所に置いていた。新しい版はこう分ける。
- 模型: C:\\LLM（自作アプリで共有。chatdraw/paths.py）
- 描いた物・保存したキャラクター: ピクチャの CharacterDesigner\\previous-version
- 部品と設定: C:\\ProgramData\\CharacterDesigner
移す物を移し終えてから、前の版の場所を丸ごと消す（残るのはプログラムと、取り直せる部品だけ）。
1 つでも移せなかったら、前の版の場所は消さずに残し、理由を記録に書く。
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

# 利用者の作った物が入る場所（前の版の build.sh の DATA から、部品と模型の .cache と models を除いた物）
WORKS = ("library", "bible", "characters", "designs", "config", "out")


def old_install() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    d = Path(base) / "Programs" / "CharacterDesigner" if base else None
    return d if d is not None and d.is_dir() else None


def pictures() -> Path:
    return Path.home() / "Pictures" / "CharacterDesigner"


def _move(src: Path, dst: Path, log: list[str]) -> bool:
    """src を dst へ移す。dst に同じ名前の物があれば、同じ物とみなして src を移さない（あとで前の場所ごと消える）"""
    if dst.exists():
        log.append(f"既にある: {dst}")
        return True
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        log.append(f"移した: {src} -> {dst}")
        return True
    except OSError as e:
        log.append(f"移せなかった: {src} ({e})")
        return False


def migrate(old: Path, hub: Path, gguf: Path, works: Path, log_path: Path) -> bool:
    """前の版の場所 old から移す。全部移せたら old を消して True を返す"""
    log: list[str] = [time.strftime("%Y-%m-%d %H:%M:%S"), f"前の版: {old}"]
    ok = True
    old_hub = old / ".cache" / "gen" / "hf" / "hub"
    if old_hub.is_dir():
        for d in sorted(old_hub.glob("models--*")):
            ok &= _move(d, hub / d.name, log)
    old_llm = old / ".cache" / "llm"
    if old_llm.is_dir():
        for f in sorted(old_llm.glob("*.gguf")):
            if f.is_symlink():
                continue   # 別名（model.gguf）は中身ではない
            ok &= _move(f, gguf / f.name, log)
    for name in WORKS:
        d = old / name
        if d.is_dir() and any(d.iterdir()):
            ok &= _move(d, works / "previous-version" / name, log)
    if ok:
        shutil.rmtree(old, ignore_errors=True)
        log.append("前の版の場所を消した" if not old.exists() else f"消せずに残った: {old}")
    else:
        log.append("移せなかった物があるので、前の版の場所は残した")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n\n")
    return ok and not old.exists()


def main(argv: list[str]) -> int:
    """インストーラーから呼ぶ入口（人は使わない）。引数があればそれを前の版の場所とする"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from chatdraw.paths import GGUF, HOME, HUB, ensure_shared
    old = Path(argv[0]) if argv else old_install()
    if old is None or not old.is_dir():
        return 0
    ensure_shared()
    return 0 if migrate(old, HUB, GGUF, pictures(), HOME / "migrate.log") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
