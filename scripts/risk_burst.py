"""Generate many payments for one customer to trigger risk velocity behavior."""

import argparse
import asyncio
from uuid import uuid4

import httpx


async def main() -> None:
    """CLI entrypoint for burst submission smoke tests."""

    parser = argparse.ArgumentParser(description="Send many payments for the same customer.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="dev-secret")
    parser.add_argument("--customer-id", default="burst-customer-1")
    parser.add_argument("--amount-cents", type=int, default=1000)
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()

    statuses: dict[int, int] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(args.count):
            payload = {
                "customer_id": args.customer_id,
                "amount_cents": args.amount_cents,
                "currency": "USD",
                "idempotency_key": f"burst-{i}-{uuid4()}",
            }
            resp = await client.post(
                f"{args.base_url}/payments",
                json=payload,
                headers={"x-api-key": args.api_key, "x-correlation-id": str(uuid4())},
            )
            statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
            print(resp.status_code, resp.text)

    print("status_counts=", statuses)


if __name__ == "__main__":
    asyncio.run(main())
