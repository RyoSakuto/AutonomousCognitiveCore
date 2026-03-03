#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Running full game tests..."
./spielpaket_vertical_slice/run_tests.sh

echo "[2/4] Running strict route-balance report..."
./spielpaket_vertical_slice/scripts/report_route_balance.py \
  --strict \
  --output spielpaket_vertical_slice/route_balance_report.json

echo "[3/4] Printing orchestrator status..."
python3 orchestrator.py status

echo "[4/4] Building release artifact..."
./scripts/build_release.sh

echo "Release-readiness checks completed successfully."
