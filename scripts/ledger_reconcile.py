"""Fetch and print ledger reconciliation report JSON."""

import argparse
import json

import httpx


def main() -> None:
    """CLI entrypoint for reconciliation checks."""

    parser = argparse.ArgumentParser(description="Fetch ledger reconciliation report endpoint.")
    parser.add_argument("--ledger-url", default="http://localhost:8004")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    resp = httpx.get(f"{args.ledger_url}/reconciliation", params={"limit": args.limit}, timeout=10.0)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
