#!/usr/bin/env bash
set -euo pipefail
python -m pip install --user 'uv==0.12.23'
export PATH="$HOME/.local/bin:$PATH"
uv sync --locked --extra dev
uv run playwright install --with-deps chromium
printf '%s\n' 'Setup complete. Start both servers with: uv run capabilities web --codespaces' 'Keep ports 8766 and 8767 Private in the Ports panel.'
