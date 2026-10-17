#!/usr/bin/env bash
# Which scenario is active, drift from the baseline, and the demo app's pods.
cd "$(dirname "$0")/.." && exec python3 12-scenarios/demo.py status
