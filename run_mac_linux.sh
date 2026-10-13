#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg'; exit 1; }
command -v ffprobe >/dev/null || { echo 'Install FFprobe'; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; echo 'Add OPENAI_API_KEY to .env and rerun'; exit 0; fi
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8765
