#!/usr/bin/env python3
"""
ARIA — Advanced Raspberry Intelligence Assistant
Entry point. All real logic lives in the bmo/ package — this file stays at
the project root (not `python -m bmo`) so that bmo/self_coder.py's dynamic
`import dynamic_skills.X` keeps resolving via sys.path[0] the same way it
always has.

Usage:
  python aria.py              # normal mode
  python aria.py --headless   # no GUI (Raspberry Pi without screen)
  python aria.py --test       # self-test and exit
"""
import sys
import argparse

from bmo.agent import ARIAAgent, run_self_test

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIA Voice Assistant")
    parser.add_argument("--headless", action="store_true",
                        help="Run without GUI (for Pi without display)")
    parser.add_argument("--test", action="store_true",
                        help="Run self-test and exit")
    args = parser.parse_args()

    if args.test:
        run_self_test()
        sys.exit(0)

    print("=== ARIA STARTING ===", flush=True)
    ARIAAgent(headless=args.headless)
