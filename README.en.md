# CharacterDesigner

The product is chatdraw, a Windows desktop app: ask in chat and the AI draws character designs and illustrations, a numeric art director inspects them, and you can draw over them by hand. Requests are not limited to Japanese.
日本語: [README.md](README.md)

All development happens in [chatdraw/](chatdraw/README.md). Setup.exe is built by `packaging/chatdraw/` and `.github/workflows/chatdraw-*.yml`.

## Install and use

- Installation, model download, update, removal and troubleshooting: [chatdraw/help/install.md](chatdraw/help/install.md) (Japanese)
- Usage: [chatdraw/help/manual.md](chatdraw/help/manual.md) (Japanese). Both open from the app's Help (ヘルプ) menu, which also has a guided tour (F1) and per-feature guides
- The models the app can run: [docs/models.md](docs/models.md)

## What the app does

The app's UI is in Japanese; entry names are given as they appear.

- Draw: the AI panel with tabs (描く内容, 作風, 模型, 詳しい設定, 加工), presets and painting styles, count, seed and reference image, voice input (🎤). おまかせ in the AI menu picks the best-rated local model and loops draw, inspect and fix
- New drawings replace the canvas (undo restores it); requests stay in the history and can be re-run from its right-click menu
- Character design menu (キャラクターデザイン): save a character sheet, turnaround (三面図), expression sheet (表情差分)
- Fix and extend: circle an area with the red pen and only that area is redrawn; open an existing image to fix it (画像を開いて直す…); clean up (綺麗にする) and outpaint (絵の外へ広げる) from the canvas right-click menu; chibi, line art, pixel art and 2x upscale from the 加工 tab; go to 3D (3D に進む…)
- Art director: hands, feet, faces, requested items and CharacterDesigner's own numeric checks run inside the おまかせ flow (`chatdraw/omakase.py`, `chatdraw/origqc.py`)
- Models: favorites, the fix model, and the model manager (模型の管理…) to fetch, update, delete, add by Hugging Face name, hide, block or stop models
- Painting: brushes, colors, layers, selection, themes, saved layouts, timelapse with GIF and video export
- Files: save, PNG and PSD export, trash (ごみ箱…), library panel, share to social sites, update check

## Content limits

Nothing is restricted up front. The single fixed limit is sexual depiction of children (`refused` in `chatdraw/engine.py`). See [docs/filters.md](docs/filters.md). A user filter panel is not in the app yet.

## Tools not yet in the app

`tools/` keeps inspection, learning and post-processing parts that are tested but not in the app; whether to bring them in is the user's decision
(list: [docs/reports/cleanup-20261031.md](docs/reports/cleanup-20261031.md), Japanese). These include the art-director measurements and learning (`tools/gen/measure.py`, `tools/gen/normlearn.py`, norms in `styles/anime-norms.json`), retouch, inking, materials, atmosphere, the language-model prompt rewriter, Blender and MakeHuman rigs, and the pixel-art tools.

```bash
PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py image.png --hair "#1e1a24,#a8203c"
```

## Directory layout

A map is in [docs/STRUCTURE.md](docs/STRUCTURE.md) (Japanese); images are listed in [library/INDEX.md](library/INDEX.md).

| Path | Role |
|---|---|
| `chatdraw/` | The product: desktop app (PySide6), tests in `chatdraw/tests/` |
| `packaging/chatdraw/` | How Setup.exe is built (run by the `chatdraw-*.yml` workflows) |
| `tools/gen/` | Drawing, redrawing and measuring. `hands.py`, `tagger.py`, `cdhome.py` ship inside the app |
| `tools/` | Pixel-art renderer, checks and comparisons |
| `styles/` | Style rules and art-director norms (numbers and sources) |
| `docs/` | Decisions, findings, roadmap |

## Development

```bash
python3 -m unittest discover -s tests
QT_QPA_PLATFORM=offscreen python3 -m unittest chatdraw.tests.test_chatdraw
```

## License

Proprietary (internal / personal use). See [LICENSE](LICENSE). Distribution plan: [docs/release-plan.md](docs/release-plan.md).
