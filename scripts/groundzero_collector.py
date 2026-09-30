#!/usr/bin/env python3
"""
GroundZero — VCF / vSphere 9.1 HCI Readiness — CLI Entry Point.

This is the primary command-line interface for the GroundZero.
All core logic is implemented in the groundzero/ package.

Usage:
    python groundzero_collector.py --targets 10.0.0.1
    python groundzero_collector.py --targets "192.168.1.0/24" --threads 8
    python -m groundzero --targets 10.0.0.1

No external dependencies. Requires Python 3.9+.
"""
import os
import sys

# Ensure groundzero package directory is in sys.path regardless of execution path or working directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
for _d in (_script_dir, _parent_dir):
    if _d and _d not in sys.path and os.path.isdir(os.path.join(_d, "groundzero")):
        sys.path.insert(0, _d)
        break

# Re-export everything so callers importing from groundzero_collector work seamlessly
from groundzero import *  # noqa: F403
from groundzero.cli import main

# Optional Service Tag feature — available when Dell TechDirect credentials are configured
from groundzero.servicetag import (  # noqa: F401
    DellTechDirectClient,
    evaluate_esa_from_components,
    summarise_warranty,
)

if __name__ == "__main__":
    main()
