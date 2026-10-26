# CharacterDesigner

A tool that draws character designs with AI, inspects them with a numeric art director, and keeps learning from verdicts and feedback.
Ask for "a character like ..." in any language; it draws an illustrated character design, then finds flaws more finely than the eye
(a face that would distort if turned to the front, a shadow brighter than the lit side, hair that drifted from the requested color) and either fixes or rejects them.
日本語: [README.md](README.md)

![The studio screen: request on the left, the large view in the middle, role progress and proposals on the right](docs/images/app-studio.jpg)

## Layout

A map of the repository is in [docs/STRUCTURE.md](docs/STRUCTURE.md) (Japanese); every image is listed with thumbnails in [library/INDEX.md](library/INDEX.md).

## Features

- Draw: illustrated character designs from a request (local image generation; the drawing step can be swapped for an external image generator). 1.5x redraw, face and hair redraw, and a finish to 4096 px on the long side (AI upscaling, then each 1024 px tile is redrawn to add detail; tiles whose shape changed are not used)
- Art director (inspection): measures face geometry, shadow order, background vs. figure lighting, hair color and left/right pairs, and lists values outside the norms. Norms are calibrated on images whose answer is known
- Retouching: photo-correction techniques (spot healing, denoising, levels, defringing, anti-aliasing, sharpening and more), each applied only after measuring that it helped and did not break the picture (`tools/gen/retouch.py`)
- Learning: re-learns the art director's norms from verdicts on drawn images and from the user's feedback, per user
- Post-processing options: chibi / deformed, pixel art, 3D, realistic — made from the finished illustration. The design itself is always decided as an illustration
- Paint board: pressure, layers, line cleanup, materials (translucent, metal, ...), atmosphere (god rays, dappled light, ...). Each AI assist can be turned on or off
- Use from Claude: an MCP server lets Claude draw, inspect, learn and finish
- Nothing is restricted up front. Users block what they do not want with their own filters. The single fixed limit is sexual depiction of children ([docs/filters.md](docs/filters.md))

## Art director: inspection by numbers

`tools/gen/measure.py` and `tools/gen/qc.py` measure what a person notices at a glance:
- Face geometry when turned back to the front, shadow order against the light, a backlit scene with a front-lit face, hair color against the requested colors, left/right pairs
- Shape and count: two legs fused into one, two bodies merged when one person was asked, one requested item drawn twice, unrequested prints, text, jackets or weapons
- Hidden parts (`tools/gen/occlusion.py`): a hand or foot that is not visible passes when hiding it is natural (out of frame, facing away, behind an object), and fails when the request needs it or the limb ends in empty background
- Comparing drawing methods: redraw the same prompts and seeds (`casts/bench-stage1.json`) and compare problem counts before and after (`tools/gen/bench.py`)

Norms live in `styles/anime-norms.json`; verdicts and user feedback re-learn them into `config/norms.user.json` (`tools/gen/normlearn.py`).

## Content limits and filters

Nothing is restricted up front; users block what they do not want with their own filters (`config/filters.json`).
The single fixed limit is sexual depiction of children. See [docs/filters.md](docs/filters.md).

## Use from Claude (MCP)

With the app running (`sh app/start.sh`), register the MCP server and ask Claude to draw:
`claude mcp add characterdesigner -e PYTHONPATH=.cache/app/lib -- python3 -m app.mcp.server`.
Call `guide` first; it returns the workflow and every tool's arguments.

## Requirements

- Python 3.10+, Node.js 20.19+, curl
- About 9 GB of disk (image model ~7 GB, language model ~1.1 GB, packages ~1 GB). Uses an NVIDIA or Apple GPU automatically when present; runs on CPU otherwise (about 5 minutes per image)
- The models the app can run (image models and language models) with size, strengths and commercial-use terms are listed in [docs/models.md](docs/models.md)

## Setup

Windows (Setup.exe):

1. Run `CharacterDesigner-Setup.exe`. It installs per user (`%LOCALAPPDATA%\Programs\CharacterDesigner`), so no administrator rights are needed. Python and Node.js are not required
2. Open CharacterDesigner on the desktop. The first start downloads the drawing packages that fit the PC's GPU (1–3 GB) and the image model (~7 GB); if less than 10 GB is free it stops and says why
3. When ready, the CharacterDesigner window opens (no browser)

Build Setup.exe on Linux with `sh packaging/windows/build.sh` (uses NSIS makensis; output goes to `dist/`).

From a clone:

1. Run `sh app/start.sh` (the first run downloads packages and models, 10–20 minutes; later starts take seconds)
2. The CharacterDesigner window opens. For a server-only run (development, MCP): `python3 app/launch.py --no-window`

## Usage

1. Write a request in "自由に描く" (free draw), press "描く言葉に直す" (convert to prompt), then "描く" (draw). Any language works; the fallback dictionary used when neither a language model nor Claude is available reads Japanese words only
2. Measure the drawn image with the art director and record a verdict; it becomes a training example
   `PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py image.png --hair "#1e1a24,#a8203c"`
   `PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py record image.png --verdict reject --by user --reason "the face is distorted"`
   `PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py learn`
3. Server: `POST /api/measure`, `POST /api/feedback`, `POST /api/learn`. MCP: `measure`, `feedback`, `learn` (call `guide` first for the full tool list)

Register the MCP server with Claude Code from the repository root:
`claude mcp add characterdesigner -e PYTHONPATH=.cache/app/lib -- python3 -m app.mcp.server`

## Configuration

| Variable | Purpose | Required |
|---|---|---|
| `CD_LLM_URL` | Local language model endpoint (OpenAI compatible) | Optional |
| `CD_LLM_MODEL` | Model name at that endpoint | Optional |
| `ANTHROPIC_API_KEY` | Read requests with Claude when no local model is available | Optional |
| `CD_DEVICE` | Where to draw (`cuda`, `mps`, `cpu`). Omitted: NVIDIA GPU, then Apple GPU, then CPU | Optional |
| `CD_TORCH` | Which torch build setup installs (`cuda`, `cpu`, `default`). Omitted: CUDA on Linux with an NVIDIA GPU, the default build on Mac, CPU elsewhere | Optional |
| `CD_APP_DATA` | Where drawn images are stored (default `.cache/app/jobs`) | Optional |
| `CD_HOME` | Where packages, models and learned norms live (default `.cache` in the repository) | Optional |

User filters live in `config/filters.json` and learned norms in `config/norms.user.json`; neither is committed.

## Directory layout

| Path | Role |
|---|---|
| `app/` | Local app: server (FastAPI), web UI (Vite + React), MCP server |
| `tools/gen/` | Drawing, redrawing and measuring: `measure.py`, `faceform.py`, `normlearn.py`, `free_text.py`, `hires.py`, `detail.py`, `upscale.py` |
| `tools/` | Pixel-art renderer, checks and comparisons |
| `styles/` | Style rules and art-director norms (numbers and sources) |
| `docs/` | Decisions, findings, roadmap, weekly comparisons with external generators |

## Development

```bash
python3 -m unittest discover -s tests
PYTHONPATH=.cache/gen/lib python3 -m pytest tests
PYTHONPATH=.cache/app/lib python3 -m pytest app/server/tests app/mcp/tests
cd app/web && npm run build
```

## License

Proprietary (internal / personal use). See [LICENSE](LICENSE). Distribution plan: [docs/release-plan.md](docs/release-plan.md).
