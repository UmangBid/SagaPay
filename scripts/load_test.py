"""Async load generator for gateway payment endpoint."""

import argparse
import asyncio
import random
import statistics
import time
from uuid import uuid4

import httpx


async def send_one(client: httpx.AsyncClient, base_url: str, api_key: str, customer_idx: int):
    """Send one payment request and return (status_code, latency_ms)."""

    started = time.perf_counter()
    payload = {
        "customer_id": f"cust-{customer_idx}",
        "amount_cents": random.randint(100, 250000),
        "currency": "USD",
        "idempotency_key": str(uuid4()),
    }
    try:
        resp = await client.post(
            f"{base_url}/payments",
            json=payload,
            headers={"x-api-key": api_key, "x-correlation-id": str(uuid4())},
        )
        latency = (time.perf_counter() - started) * 1000
        return resp.status_code, latency
    except Exception:
        latency = (time.perf_counter() - started) * 1000
        return 599, latency


async def run(total: int, concurrency: int, base_url: str, api_key: str):
    """Execute a bounded-concurrency load run and print summary stats."""

    sem = asyncio.Semaphore(concurrency)
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def worker(i: int):
            async with sem:
                return await send_one(client, base_url, api_key, i % 500)

        tasks = [asyncio.create_task(worker(i)) for i in range(total)]
        for task in asyncio.as_completed(tasks):
            results.append(await task)

    codes = [c for c, _ in results]
    lats = [latency for _, latency in results]
    success = sum(1 for c in codes if 200 <= c < 300)
    errors = total - success

    def pct(values, p):
        """Simple percentile helper for sorted latency values."""

        if not values:
            return 0.0
        idx = min(len(values) - 1, max(0, int((p / 100.0) * len(values)) - 1))
        return sorted(values)[idx]

    print(f"total={total}")
    print(f"success={success}")
    print(f"errors={errors}")
    print(f"error_rate={(errors / total) * 100:.2f}%")
    print(f"p50_ms={pct(lats, 50):.2f}")
    print(f"p95_ms={pct(lats, 95):.2f}")
    print(f"p99_ms={pct(lats, 99):.2f}")
    print(f"avg_ms={statistics.mean(lats):.2f}")


if __name__ == "__main__":
    # CLI entrypoint used in README load-test examples.
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="dev-secret")
    args = parser.parse_args()
    asyncio.run(run(args.total, args.concurrency, args.base_url, args.api_key))
