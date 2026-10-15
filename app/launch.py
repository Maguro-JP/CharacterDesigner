"""アプリを1つで起動する。Windows の配布版（Setup.exe で入れたもの）と、手元の clone の両方で同じものを使う。

1. 足りない部品を入れる（初回だけ。描く部品 約 1〜3GB、タグを読む模型 約 380MB）
2. 絵の模型が手元に無ければ取る（約 7GB。先に空きを確かめ、足りなければ取らずに理由を出す）
3. サーバーを起こし、画面（同じ窓口で配る）をブラウザーで開く

  python app/launch.py              入れて、起こして、開く
  python app/launch.py --setup      入れるだけ
  python app/launch.py --no-browser ブラウザーを開かない

配布版では、入れた場所の .cache に部品と模型を置く。利用者ごとの場所（%LOCALAPPDATA%\\Programs）に入れるので、管理者の権限は要らない。
言葉の模型（llama.cpp）は配布版には入れない。Ollama や LM Studio を使うなら CD_LLM_URL と CD_LLM_MODEL を渡す。無ければ辞書で読む。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("CD_PORT", "8000"))
# 絵の模型 約 7GB に、取る途中の一時ファイルと描いた絵の分を足した空き
MODEL_NEED_GB = 10


# Windows の窓は既定で日本語を書けない文字コード（cp1252 など）のことがある。書けずに落ちないよう UTF-8 にそろえる
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def run(args: list[str], env: dict | None = None) -> None:
    r = subprocess.run(args, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise SystemExit(f"失敗しました（終了コード {r.returncode}）: {' '.join(args)}")


def setup() -> None:
    lib = ROOT / ".cache" / "app" / "lib"
    if not (lib / "fastapi").exists():
        say("サーバーの部品")
        run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--target", str(lib),
             "-r", str(ROOT / "app" / "server" / "requirements.txt")])
    say("描く部品（初回だけ。数分〜数十分）")
    run([sys.executable, str(ROOT / "tools" / "gen" / "setup.py")])


def ensure_model() -> bool:
    """作風 anime に割り当てた模型が手元に無ければ取る。取れないときは理由を出して False を返す（画面は開く）"""
    gen = str(ROOT / "tools" / "gen")
    env = {"PYTHONPATH": os.pathsep.join([str(ROOT / ".cache" / "gen" / "lib"), gen])}
    probe = subprocess.run([sys.executable, "-c", "import json, models; c = models.check(models.for_style('anime'));"
                            "print(json.dumps(c, ensure_ascii=False))"],
                           env={**os.environ, **env}, capture_output=True, text=True)
    if probe.returncode != 0:
        print(probe.stderr, file=sys.stderr)
        return False
    import json
    c = json.loads(probe.stdout.strip().splitlines()[-1])
    if c["usable"]:
        return True
    if c.get("form") != "huggingface":
        print(f"絵の模型「{c['name']}」は使えません: {c.get('reason')}", file=sys.stderr)
        return False
    free = shutil.disk_usage(ROOT).free / 1e9
    if free < MODEL_NEED_GB:
        print(f"絵の模型（約 7GB）を取るには空きが {MODEL_NEED_GB}GB 要ります。今は {free:.1f}GB です。"
              f"空きを作ってから起動し直してください。", file=sys.stderr)
        return False
    say(f"絵の模型 {c['name']}（約 7GB。初回だけ。回線によって 10 分〜1 時間）")
    run([sys.executable, str(ROOT / "tools" / "gen" / "models.py"), "fetch", c["name"]], env={**env, "CD_FETCH": "1"})
    return True


def open_when_ready(url: str) -> None:
    for _ in range(240):
        try:
            urllib.request.urlopen(url + "api/cases", timeout=2)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(1)


def serve(browser: bool) -> None:
    for p in (ROOT / ".cache" / "app" / "lib", ROOT / ".cache" / "gen" / "lib", ROOT):
        sys.path.insert(0, str(p))
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
    url = f"http://127.0.0.1:{PORT}/"
    say(f"起動します。開く: {url}（止めるときはこの窓を閉じるか Ctrl-C）")
    if browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    import uvicorn
    uvicorn.run("app.server.main:app", host="127.0.0.1", port=PORT)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="入れるだけで起動しない")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    os.chdir(ROOT)
    setup()
    ok = ensure_model()
    if a.setup:
        say("部品はそろいました" if ok else "絵の模型がまだありません（上の理由を見てください）")
        return
    if not ok:
        print("絵の模型が無いので、描く仕事は失敗します。画面は開きます。", file=sys.stderr)
    serve(not a.no_browser)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # 配布版はダブルクリックで開いた窓なので、失敗の理由を読めるよう閉じる前に待つ
        if e.code not in (0, None) and os.environ.get("CD_PAUSE_ON_ERROR") == "1":
            print(e.code, file=sys.stderr)
            input("Enter で閉じます")
        raise
