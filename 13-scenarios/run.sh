#!/usr/bin/env bash
# Step 12: inject / reset failure scenarios. Arguments go to demo.py:
#   ./13-scenarios/run.sh inject 01-oomkilled     (default: list)
cd "$(dirname "$0")/.." && exec python3 13-scenarios/demo.py "${@:-list}"
