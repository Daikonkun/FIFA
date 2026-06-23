from __future__ import annotations

import argparse

from fifa_arb_agent.agent import run_agent
from fifa_arb_agent.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="FIFA 2026 Polymarket probability scanner.")
    parser.add_argument("--dry-run", action="store_true", help="Print report without Telegram delivery.")
    args = parser.parse_args()

    settings = load_settings()
    print(run_agent(settings, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
