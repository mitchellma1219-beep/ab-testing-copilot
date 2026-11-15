#!/usr/bin/env python3
"""Skill entry point: forwards to the ab_testing_copilot CLI.

Commands: plan, design, sequential, analyze, aa, srm, simulate. Run ``<command> --help`` for
the options of each. Works from the installed package or from a repository checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from ab_testing_copilot.cli import main
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from ab_testing_copilot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
