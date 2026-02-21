"""Publish a raw JSON event directly to a Kafka topic.

Useful for manual fault-injection and duplicate-event testing.
"""

import argparse
import asyncio
import json
from pathlib import Path

from aiokafka import AIOKafkaProducer


async def publish(bootstrap_servers: str, topic: str, payload: dict) -> None:
    """Open producer, publish one message, close producer."""

    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    await producer.start()
    try:
        await producer.send_and_wait(topic, json.dumps(payload).encode("utf-8"))
    finally:
        await producer.stop()


def main() -> None:
    """Parse CLI args and publish one JSON payload."""

    parser = argparse.ArgumentParser(description="Publish a raw JSON event to Kafka topic.")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--json", dest="json_inline", default=None, help="Inline JSON payload")
    parser.add_argument("--file", dest="json_file", default=None, help="Path to JSON file")
    args = parser.parse_args()

    if bool(args.json_inline) == bool(args.json_file):
        raise SystemExit("Provide exactly one of --json or --file")

    if args.json_inline:
        payload = json.loads(args.json_inline)
    else:
        payload = json.loads(Path(args.json_file).read_text())

    asyncio.run(publish(args.bootstrap_servers, args.topic, payload))
    print(f"Published to topic={args.topic}")


if __name__ == "__main__":
    main()
