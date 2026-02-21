"""Kafka envelope + producer/consumer helpers.

This module standardizes event structure, metadata propagation, and resilient
consumer loops used by every service.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import BaseModel, Field

from finpay.common.config import settings
from finpay.common.logging import event_id_ctx, logger, payment_id_ctx, trace_id_ctx
from finpay.common.metrics import event_queue_delay_seconds


class EventEnvelope(BaseModel):
    """Canonical event shape sent across Kafka topics."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    aggregate_id: str
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str
    payload: dict[str, Any]


class KafkaBus:
    """Lazy Kafka producer wrapper used by service outbox publishers."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
            await self._producer.start()
        return self._producer

    async def publish(self, topic: str, event: EventEnvelope) -> None:
        producer = await self.producer()
        await producer.send_and_wait(topic, json.dumps(event.model_dump()).encode("utf-8"))

    async def close(self) -> None:
        if self._producer:
            await self._producer.stop()


async def make_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    """Create a configured Kafka consumer for one topic/group."""

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    return consumer


async def consume_forever(
    topic: str,
    group_id: str,
    handler,
) -> None:
    """Continuously consume one topic and pass parsed envelopes to `handler`.

    Errors in individual messages are logged and processing continues; commit is
    done in batches to keep throughput reasonable.
    """

    while True:
        consumer = None
        try:
            consumer = await make_consumer(topic, group_id)
            while True:
                results = await consumer.getmany(timeout_ms=500, max_records=50)
                for _, messages in results.items():
                    for msg in messages:
                        try:
                            payload = json.loads(msg.value.decode("utf-8"))
                            event = EventEnvelope(**payload)
                            occurred_at_raw = event.occurred_at.replace("Z", "+00:00")
                            occurred_at = datetime.fromisoformat(occurred_at_raw)
                            delay_seconds = max(
                                0.0,
                                (datetime.now(timezone.utc) - occurred_at.astimezone(timezone.utc)).total_seconds(),
                            )
                            event_queue_delay_seconds.labels(
                                service=settings.service_name,
                                topic=topic,
                            ).observe(delay_seconds)
                            trace_token = trace_id_ctx.set(event.trace_id)
                            event_token = event_id_ctx.set(event.event_id)
                            payment_token = payment_id_ctx.set(event.aggregate_id)
                            try:
                                logger.info(
                                    "event_received topic=%s group=%s event_type=%s aggregate_id=%s",
                                    topic,
                                    group_id,
                                    event.event_type,
                                    event.aggregate_id,
                                )
                                await handler(event)
                            finally:
                                trace_id_ctx.reset(trace_token)
                                event_id_ctx.reset(event_token)
                                payment_id_ctx.reset(payment_token)
                        except Exception as exc:
                            logger.error(
                                "handler_error topic=%s group=%s offset=%s error=%s",
                                topic,
                                group_id,
                                msg.offset,
                                exc,
                            )
                await consumer.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("consumer_loop_error topic=%s group=%s error=%s", topic, group_id, exc)
            await asyncio.sleep(2)
        finally:
            if consumer is not None:
                await consumer.stop()
            await asyncio.sleep(0)
