"""アプリを1つで起動する。Windows の配布版（Setup.exe で入れたもの）と、手元の clone の両方で同じものを使う。

1. 足りない部品を入れる（初回だけ。描く部品 約 1〜3GB、タグを読む模型 約 380MB）
2. 絵の模型が手元に無ければ取る（約 7GB。先に空きを確かめ、足りなければ取らずに理由を出す）
3. サーバーを起こし、画面（同じ窓口で配る）をブラウザーで開く

  python app/launch.py              入れて、起こして、開く
  python app/launch.py --setup      入れるだけ
  python app/launch.py --no-browser ブラウザーを開かない

配布版では、入れた場所の .cache に部品と模型を置く。利用者ごとの場所（%LOCALAPPDATA%\\Programs）に入れるので、管理者の権限は要らない。
初回の起動では、大きな取り物（絵の模型、言葉の模型）を取るかどうかを1つずつ聞き、答えを <置き場所>/choices.json に残す。
2回目からは聞かない。選び直すときは --choose を付ける。聞かずに全部取るときは --yes。
言葉の模型（llama.cpp と Qwen2.5 の GGUF）を取ったら、起動のたびに 8081 番で起こす。Ollama や LM Studio を使うなら
CD_LLM_URL と CD_LLM_MODEL を渡す（そのときは取らない・起こさない）。言葉の模型が無ければ日本語の頼みは辞書で読む。
"""
from __future__ import annotations

import argparse
import json
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
# 部品と模型の置き場所。決め方は tools/gen/cdhome.py と同じ（起動は部品を入れる前に動くので、そちらを読まずに同じ式で持つ）
HOME = Path(os.environ.get("CD_HOME") or ROOT / ".cache")
PORT = int(os.environ.get("CD_PORT", "8000"))
# 絵の模型 約 7GB に、取る途中の一時ファイルと描いた絵の分を足した空き
MODEL_NEED_GB = 10
CHOICES = HOME / "choices.json"
LLM_DIR = HOME / "llm"
LLM_PORT = 8081
# 言葉の模型の大きさ。Qwen2.5 の指示に従う版（Apache-2.0、日本語が読める）。大きいほど読み違いが減り、遅くなる
LLM_SIZES = {
    "small": ("約 0.5GB", "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"),
    "default": ("約 1.1GB", "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"),
}


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
    lib = HOME / "app" / "lib"
    if not (lib / "fastapi").exists():
        say("サーバーの部品")
        run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--target", str(lib),
             "-r", str(ROOT / "app" / "server" / "requirements.txt")])
    say("描く部品（初回だけ。数分〜数十分）")
    run([sys.executable, str(ROOT / "tools" / "gen" / "setup.py")])


def ask(question: str, options: list[tuple[str, str]], default: str, auto: bool) -> str:
    """番号で選ばせる。--yes なら既定を選ぶ。入力が読めない（窓が無い）ときも既定"""
    if auto:
        return default
    print(f"\n{question}")
    for i, (key, label) in enumerate(options, 1):
        print(f"  {i}. {label}{'（既定）' if key == default else ''}")
    try:
        got = input("番号を入れて Enter（そのまま Enter で既定）: ").strip()
    except EOFError:
        return default
    if got.isdigit() and 1 <= int(got) <= len(options):
        return options[int(got) - 1][0]
    return default


def choose(again: bool, auto: bool) -> dict:
    """初回だけ、取る物を選ばせて残す。2回目からは残した答えを使う"""
    if CHOICES.exists() and not again:
        try:
            return json.loads(CHOICES.read_text(encoding="utf-8"))
        except ValueError:
            pass
    free = shutil.disk_usage(ROOT).free / 1e9
    say(f"初回の設定（空き {free:.0f}GB。あとで選び直すときは --choose を付けて起動）")
    c = {
        "image_model": ask("絵の模型（約 7GB）を取りますか。取らないと絵は描けません。",
                           [("yes", "取る"), ("no", "取らない")], "yes", auto) == "yes",
        "llm": ask("言葉の模型を取りますか。日本語の頼みを描く言葉に直します。取らなければ辞書で読みます。",
                   [("default", f"取る（標準、{LLM_SIZES['default'][0]}）"), ("small", f"取る（小さい版、{LLM_SIZES['small'][0]}。メモリ 8GB 以下の PC 向け）"),
                    ("no", "取らない")], "default", auto),
    }
    if os.environ.get("CD_LLM_URL"):
        c["llm"] = "no"  # 手持ちの窓口（Ollama など）を使う
    CHOICES.parent.mkdir(parents=True, exist_ok=True)
    CHOICES.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def fetch(url: str, dest: Path) -> None:
    """途中で切れても次の起動で取り直せるよう、.part に書いてから名前を変える。進みを 5% ごとに出す"""
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(part, "wb") as f:
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -5
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= shown + 5:
                shown = done * 100 // total
                print(f"  {shown}%（{done / 1e9:.2f} / {total / 1e9:.2f}GB）", flush=True)
    part.replace(dest)


def ensure_llm(size: str) -> bool:
    """言葉の模型の部品（llama-cpp-python の組み済みの配布物）と GGUF を取る。取れなければ理由を出して False"""
    lib = LLM_DIR / "lib"
    if not (lib / "llama_cpp" / "__init__.py").exists():
        say("言葉の模型の部品（llama-cpp-python）")
        # 元のソースから組むと C++ の組み立てに数十分かかり、Windows では組み立ての道具も要るので、組み済みのものだけを使う
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--target", str(lib),
                            "--only-binary", "llama-cpp-python", "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu",
                            "llama-cpp-python[server]>=0.3.16"])
        if r.returncode != 0:
            print("言葉の模型の部品を入れられませんでした。日本語の頼みは辞書で読みます。", file=sys.stderr)
            return False
    label, url = LLM_SIZES[size]
    gguf = LLM_DIR / url.rsplit("/", 1)[1]
    if not gguf.exists():
        say(f"言葉の模型 {gguf.name}（{label}。初回だけ）")
        try:
            fetch(url, gguf)
        except OSError as e:
            print(f"言葉の模型を取れませんでした（{e}）。次の起動で取り直します。", file=sys.stderr)
            return False
    (LLM_DIR / "default.txt").write_text(gguf.name, encoding="utf-8")
    return True


def start_llm() -> subprocess.Popen | None:
    """取った GGUF を全部1つの窓口（8081 番）に並べて起こす。先頭が既定。画面で選ぶと窓口が読み替える"""
    if os.environ.get("CD_LLM_URL") or not (LLM_DIR / "lib" / "llama_cpp").exists():
        return None
    files = sorted(LLM_DIR.glob("*.gguf"))
    if not files:
        return None
    first = (LLM_DIR / "default.txt").read_text(encoding="utf-8").strip() if (LLM_DIR / "default.txt").exists() else ""
    files.sort(key=lambda p: p.name != first)
    conf = {"host": "127.0.0.1", "port": LLM_PORT, "models": [{"model": str(p), "model_alias": p.stem, "n_ctx": 4096} for p in files]}
    (LLM_DIR / "server.json").write_text(json.dumps(conf, indent=1), encoding="utf-8")
    log = open(LLM_DIR / "server.log", "w", encoding="utf-8")
    say(f"言葉の模型を起こします（{files[0].stem}、{LLM_PORT} 番）")
    return subprocess.Popen([sys.executable, "-m", "llama_cpp.server", "--config_file", str(LLM_DIR / "server.json")],
                            env={**os.environ, "PYTHONPATH": str(LLM_DIR / "lib")}, stdout=log, stderr=subprocess.STDOUT)


def ensure_model() -> bool:
    """作風 anime に割り当てた模型が手元に無ければ取る。取れないときは理由を出して False を返す（画面は開く）"""
    gen = str(ROOT / "tools" / "gen")
    env = {"PYTHONPATH": os.pathsep.join([str(HOME / "gen" / "lib"), gen])}
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
    for p in (HOME / "app" / "lib", HOME / "gen" / "lib", ROOT):
        sys.path.insert(0, str(p))
    os.environ.setdefault("HF_HOME", str(HOME / "gen" / "hf"))
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
    ap.add_argument("--choose", action="store_true", help="取る物を選び直す")
    ap.add_argument("--yes", action="store_true", help="聞かずに既定（全部取る）で進める")
    a = ap.parse_args()
    os.chdir(ROOT)
    c = choose(a.choose, a.yes)
    setup()
    ok = ensure_model() if c["image_model"] else False
    if c["llm"] != "no":
        ensure_llm(c["llm"])
    if a.setup:
        say("部品はそろいました" if ok else "絵の模型がまだありません（上の理由を見てください）")
        return
    if not ok:
        print("絵の模型が無いので、描く仕事は失敗します。画面は開きます（--choose で取り直せます）。", file=sys.stderr)
    llm = start_llm()
    try:
        serve(not a.no_browser)
    finally:
        if llm:
            llm.terminate()


if __name__ == "__main__":
    # 道具の中はファイルを文字コードの指定なしで読む所が多い。Windows の既定（cp1252、cp932）では日本語の設定が読めずに落ちたので、
    # Python の UTF-8 モードで動かし直す。子の処理（部品の取得、模型の確認）にも環境変数で引き継がれる
    if not sys.flags.utf8_mode:
        os.environ["PYTHONUTF8"] = "1"
        sys.exit(subprocess.run([sys.executable, "-X", "utf8", *sys.argv]).returncode)
    try:
        main()
    except SystemExit as e:
        # 配布版はダブルクリックで開いた窓なので、失敗の理由を読めるよう閉じる前に待つ
        if e.code not in (0, None) and os.environ.get("CD_PAUSE_ON_ERROR") == "1":
            print(e.code, file=sys.stderr)
            input("Enter で閉じます")
        raise
