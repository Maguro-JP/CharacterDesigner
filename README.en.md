# CharacterDesigner

The product is the desktop app chatdraw (a Windows PySide6 app: ask in chat and the AI draws, then draw over it by hand).
All development happens in [chatdraw/](chatdraw/README.md). Setup.exe is built by `packaging/chatdraw/` and `.github/workflows/chatdraw-*.yml`.
日本語: [README.md](README.md)

The app draws character designs with AI, inspects them with a numeric art director, and keeps learning from verdicts and feedback.
The other tools kept in `tools/` are inspection, learning and post-processing parts not yet in the app; whether to bring them in is the user's decision
(list: [docs/reports/cleanup-20261031.md](docs/reports/cleanup-20261031.md), Japanese).

## Layout

A map of the repository is in [docs/STRUCTURE.md](docs/STRUCTURE.md) (Japanese); every image is listed with thumbnails in [library/INDEX.md](library/INDEX.md).

## Setup

Windows (Setup.exe): installation, model download, update, removal and troubleshooting are in [chatdraw/help/install.md](chatdraw/help/install.md) (Japanese); usage is in [chatdraw/help/manual.md](chatdraw/help/manual.md). Both open from the app's Help menu.
The models the app can run are listed in [docs/models.md](docs/models.md).

## Art director: inspection by numbers

`tools/gen/measure.py` and `tools/gen/qc.py` measure what a person notices at a glance:
- Face geometry when turned back to the front, shadow order against the light, a backlit scene with a front-lit face, hair color against the requested colors, left/right pairs
- Shape and count: two legs fused into one, two bodies merged when one person was asked, one requested item drawn twice, unrequested prints, text, jackets or weapons
- Hidden parts (`tools/gen/occlusion.py`)
- Comparing drawing methods (`tools/gen/bench.py`, prompts and seeds in `casts/bench-stage1.json`)

Norms live in `styles/anime-norms.json`; verdicts and user feedback re-learn them into `config/norms.user.json` (`tools/gen/normlearn.py`).

```bash
PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py image.png --hair "#1e1a24,#a8203c"
PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py record image.png --verdict reject --by user --reason "the face is distorted"
PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py learn
```

## Content limits and filters

Nothing is restricted up front; users block what they do not want with their own filters.
The single fixed limit is sexual depiction of children. See [docs/filters.md](docs/filters.md).

## Directory layout

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
