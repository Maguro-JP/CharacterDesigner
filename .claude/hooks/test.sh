#!/usr/bin/env bash
# 止まる前に走るテスト
# 落ちたら exit 2 で止め、出力を Claude に返す。通れば黙る。
# コマンドは bootstrap.sh が推定した。違っていればここを直す。
set -uo pipefail
input="$(cat)"
# 自分が止めた直後の再実行では走らない（無限ループ防止）
case "$input" in *'"stop_hook_active":true'*) exit 0;; esac
cd "$(git rev-parse --show-toplevel)"
# 描画器の試験（tests/）。落ちたら出力を返して止める
# 描く部品（.cache/gen/lib）があれば通す。通さないと scipy や torch を使う試験が黙って飛ばされ、落ちても気付かなかった
lib=""; [ -d .cache/gen/lib/scipy ] && lib=".cache/gen/lib"
out="$(PYTHONPATH=$lib python3 -m unittest discover -s tests -q 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
# 描画アプリ（chatdraw）の試験。ここに入れていなかったため、「描く」を押すと落ちる不具合を通したままマージした
if [ -d .cache/simple/lib/PySide6 ]; then
  out="$(CD_ASSUME_FREE_RAM_GB=64 QT_QPA_PLATFORM=offscreen PYTHONPATH=.cache/simple/lib:$lib python3 -m unittest chatdraw.tests.test_chatdraw chatdraw.tests.test_presetui chatdraw.tests.test_modeldoc chatdraw.tests.test_drawbugs chatdraw.tests.test_ownstyle chatdraw.tests.test_uifix chatdraw.tests.test_features chatdraw.tests.test_freeze chatdraw.tests.test_quality chatdraw.tests.test_perfamily chatdraw.tests.test_omakase chatdraw.tests.test_editing chatdraw.tests.test_modelblock chatdraw.tests.test_modelmgr chatdraw.tests.test_aitabs chatdraw.tests.test_original_finish chatdraw.tests.test_original_qc chatdraw.tests.test_panels chatdraw.tests.test_keepsettings chatdraw.tests.test_aiui chatdraw.tests.test_stop chatdraw.tests.test_shortcuts chatdraw.tests.test_works chatdraw.tests.test_toplayer chatdraw.tests.test_logo chatdraw.tests.test_nojson chatdraw.tests.test_voicechat chatdraw.tests.test_memory chatdraw.tests.test_membudget chatdraw.tests.test_usability chatdraw.tests.test_finish_quality chatdraw.tests.test_words chatdraw.tests.test_nobreak chatdraw.tests.test_variety chatdraw.tests.test_layercrash chatdraw.tests.test_tabkey chatdraw.tests.test_confirm chatdraw.tests.test_redpeninput chatdraw.tests.test_sanity chatdraw.tests.test_seamfix chatdraw.tests.test_savefmt chatdraw.tests.test_typeguard chatdraw.tests.test_childsafe chatdraw.tests.test_sent chatdraw.tests.test_comfyui_ui chatdraw.tests.test_menuaudit chatdraw.tests.test_lora chatdraw.tests.test_obey chatdraw.tests.test_finish2 chatdraw.tests.test_quality2 chatdraw.tests.test_layerkeep chatdraw.tests.test_charafile chatdraw.tests.test_qc3 chatdraw.tests.test_redlayer chatdraw.tests.test_director chatdraw.tests.test_fixfx chatdraw.tests.test_chatfix chatdraw.tests.test_redpen3 chatdraw.tests.test_modes chatdraw.tests.test_accuracy 2>&1)" || { echo "$out" | grep -E -A12 "^(FAIL|ERROR):" | head -80 >&2; echo "$out" | tail -4 >&2; exit 2; }
  # 窓の枠のテーマの試験は、ほかの試験が数百の窓を開け閉めしたあとに流すと Qt の中で落ちる（単独では通る）。窓の状態を持ち越さないよう、別の処理で流す
  # 表示の回転の試験（test_viewtools）も、数百の窓を開け閉めしたあとに Ctrl+\ を押すと Qt の中で落ちる（単独では通る）。同じ理由で別に流す
  out="$(CD_ASSUME_FREE_RAM_GB=64 QT_QPA_PLATFORM=offscreen PYTHONPATH=.cache/simple/lib:$lib python3 -m unittest chatdraw.tests.test_menuedit chatdraw.tests.test_viewtools 2>&1)" || { echo "$out" | grep -E -A12 "^(FAIL|ERROR):" | head -80 >&2; echo "$out" | tail -4 >&2; exit 2; }
fi
exit 0
