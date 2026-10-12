# CharacterDesigner

A tool that draws character designs with AI, inspects them with a numeric art director, and keeps learning from verdicts and feedback.
Ask for "a character like ..." in any language; it draws an illustrated character design, then finds flaws more finely than the eye
(a face that would distort if turned to the front, a shadow brighter than the lit side, hair that drifted from the requested color) and either fixes or rejects them.
日本語: [README.md](README.md)

![The studio screen: request on the left, the large view in the middle, role progress and proposals on the right](docs/images/app-studio.jpg)

## Features

- Draw: illustrated character designs from a request (local image generation; the drawing step can be swapped for an external image generator). 1.5x redraw, face and hair redraw, upscaling to 4K
- Art director (inspection): measures face geometry, shadow order, background vs. figure lighting, hair color and left/right pairs, and lists values outside the norms. Norms are calibrated on images whose answer is known
- Learning: re-learns the art director's norms from verdicts on drawn images and from the user's feedback, per user
- Post-processing options: chibi / deformed, pixel art, 3D, realistic — made from the finished illustration. The design itself is always decided as an illustration
- Paint board: pressure, layers, line cleanup, materials (translucent, metal, ...), atmosphere (god rays, dappled light, ...). Each AI assist can be turned on or off
- Use from Claude: an MCP server lets Claude draw, inspect, learn and finish
- Nothing is restricted up front. Users block what they do not want with their own filters. The single fixed limit is sexual depiction of children ([docs/filters.md](docs/filters.md))

## Requirements

- Python 3.10+, Node.js 20.19+, curl
- About 9 GB of disk (image model ~7 GB, language model ~1.1 GB, packages ~1 GB). Runs on CPU without a GPU (about 5 minutes per image)

## Setup

1. Run `sh app/start.sh` (the first run downloads packages and models, 10–20 minutes; later starts take seconds)
2. Open `http://127.0.0.1:4173/`

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
| `CD_APP_DATA` | Where drawn images are stored (default `.cache/app/jobs`) | Optional |

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
