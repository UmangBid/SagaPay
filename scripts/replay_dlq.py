"""Replay one DLQ envelope back to its original topic.

Replay keeps the same failed event payload, so inbox dedupe guarantees still
apply in consumers.
"""

import argparse
import asyncio
import json
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


async def replay_once(
    bootstrap_servers: str,
    dlq_topic: str,
    target_event_id: str | None,
    target_aggregate_id: str | None,
    dry_run: bool,
    timeout_seconds: int,
) -> int:
    """Find one matching DLQ event and replay it (or dry-run)."""

    if not target_event_id and not target_aggregate_id:
        raise ValueError("Provide --event-id or --aggregate-id")

    consumer = AIOKafkaConsumer(
        dlq_topic,
        bootstrap_servers=bootstrap_servers,
        group_id=f"dlq-replay-{uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    await consumer.start()
    await producer.start()
    try:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            results = await consumer.getmany(timeout_ms=1000, max_records=200)
            for _, messages in results.items():
                for msg in messages:
                    event = json.loads(msg.value.decode("utf-8"))
                    event_id = event.get("event_id")
                    aggregate_id = event.get("aggregate_id")
                    if target_event_id and event_id != target_event_id:
                        continue
                    if target_aggregate_id and aggregate_id != target_aggregate_id:
                        continue

                    payload = event.get("payload", {})
                    replay_topic = payload.get("replay_topic")
                    failed_event = payload.get("failed_event")
                    if not replay_topic or not isinstance(failed_event, dict):
                        print("Matched DLQ event is not replayable (missing replay_topic/failed_event).")
                        return 2

                    encoded = json.dumps(failed_event).encode("utf-8")
                    print(
                        f"Matched DLQ event_id={event_id} aggregate_id={aggregate_id} "
                        f"-> replay_topic={replay_topic}"
                    )
                    if dry_run:
                        print("Dry run only; no publish performed.")
                        return 0

                    await producer.send_and_wait(replay_topic, encoded)
                    print(
                        "Replayed original failed event with same event_id="
                        f"{failed_event.get('event_id')}"
                    )
                    return 0

        print("No matching DLQ event found before timeout.")
        return 1
    finally:
        await consumer.stop()
        await producer.stop()


def main() -> None:
    """CLI entrypoint for safe DLQ replay tests."""

    parser = argparse.ArgumentParser(description="Replay one DLQ message back to its source topic.")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--dlq-topic", default="payments.dlq")
    parser.add_argument("--event-id", default=None, help="DLQ envelope event_id to replay")
    parser.add_argument("--aggregate-id", default=None, help="DLQ aggregate_id to replay")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()

    rc = asyncio.run(
        replay_once(
            bootstrap_servers=args.bootstrap_servers,
            dlq_topic=args.dlq_topic,
            target_event_id=args.event_id,
            target_aggregate_id=args.aggregate_id,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout_seconds,
        )
    )
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
