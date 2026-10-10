#!/bin/sh
# 手元の言葉の模型を入れる（docs/app/PLAN.md の M6）。日本語の頼みごとを描く言葉に直すのに使う。
#
#   sh tools/llm/setup.sh             llama-cpp-python（組み済みの配布物）と既定の模型を .cache/llm に取る
#   CD_LLM_SIZE=small sh tools/llm/setup.sh   小さい模型（約 0.5GB）にする。ディスクやメモリが少ない PC 向け
#   CD_LLM_GGUF_URL=<GGUF の URL> sh tools/llm/setup.sh   模型を選んで取る
#
# Ollama や LM Studio を既に使っているなら、これは要らない。CD_LLM_URL と CD_LLM_MODEL で窓口を教える
#（例: CD_LLM_URL=http://127.0.0.1:11434/v1 CD_LLM_MODEL=qwen2.5:7b sh app/start.sh）。
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/.cache/llm"
mkdir -p "$DIR"

# 既定は Qwen2.5 の指示に従う版（Apache-2.0、日本語が読める）。大きいほど読み違いが減り、遅くなる
case "${CD_LLM_SIZE:-default}" in
  small) URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" ;;  # 約 0.5GB
  large) URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf" ;;      # 約 2GB
  *)     URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf" ;;    # 約 1.1GB
esac
URL="${CD_LLM_GGUF_URL:-$URL}"

if [ ! -f "$DIR/lib/llama_cpp/__init__.py" ]; then
  echo "== llama-cpp-python（CPU 用の組み済みの配布物）を $DIR/lib に入れる"
  # 元のソースから組むと C++ の組み立てに数十分かかるので、組み済みのもの（--only-binary）だけを使う
  python3 -m pip install -q --target "$DIR/lib" --only-binary llama-cpp-python \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    "llama-cpp-python[server]>=0.3.16"
fi

NAME="$(basename "$URL")"
if [ ! -f "$DIR/$NAME" ]; then
  echo "== 模型 $NAME を取る"
  curl -fL --retry 3 -o "$DIR/$NAME.part" "$URL"
  mv "$DIR/$NAME.part" "$DIR/$NAME"
fi
# app/start.sh はこの名前の模型を起こす（取り替えたら、ここを指し直すだけでよい）
ln -sf "$NAME" "$DIR/model.gguf"
echo "== 入った: $DIR/model.gguf -> $NAME"
