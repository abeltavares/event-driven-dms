import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer

from .config import get_settings
from .connection_manager import manager

logger = logging.getLogger(__name__)
settings = get_settings()


class WebSocketKafkaConsumer:
    """Async Kafka consumer for WebSocket broadcasts."""

    def __init__(self):
        self.consumer: AIOKafkaConsumer | None = None
        self.running = False
        self._consume_task = None

    async def start(self):
        """Start consuming Kafka events."""
        logger.info("Starting Kafka consumer for WebSocket broadcasts...")

        try:
            self.consumer = AIOKafkaConsumer(
                settings.cdc_documents_topic,
                settings.cdc_signatures_topic,
                bootstrap_servers=settings.kafka_bootstrap_servers,
                group_id=settings.kafka_consumer_group,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )

            await self.consumer.start()

            logger.info("Kafka consumer created")
            logger.info(f"Topics: {settings.cdc_documents_topic}, {settings.cdc_signatures_topic}")
            logger.info(f"Consumer group: {settings.kafka_consumer_group}")

            self.running = True

            # Start consuming loop
            self._consume_task = asyncio.create_task(self._consume_loop())

            logger.info("Kafka consumer started successfully")

        except Exception as e:
            logger.exception(f"Failed to start Kafka consumer: {e}")
            raise

    async def _consume_loop(self):
        """Async consuming loop for Kafka messages."""
        logger.info("Kafka consuming loop started")

        message_count = 0

        try:
            async for msg in self.consumer:
                if not self.running:
                    break

                message_count += 1

                logger.debug(
                    f"Received message #{message_count} from "
                    f"{msg.topic} partition {msg.partition} offset {msg.offset}"
                )

                try:
                    if msg.topic == settings.cdc_documents_topic:
                        await self._process_document_event(msg.value)
                    elif msg.topic == settings.cdc_signatures_topic:
                        await self._process_signature_event(msg.value)
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)

        except Exception as e:
            logger.exception(f"Error in consume loop: {e}")
        finally:
            logger.info(f"Kafka consuming loop stopped (processed {message_count} messages)")

    async def _process_document_event(self, value: dict[str, Any]):
        """Process document CDC event and broadcast to WebSocket clients."""
        try:
            op = value.get("op")
            after = value.get("after", {})
            before = value.get("before", {})

            document_id = after.get("id") or before.get("id")

            if not document_id:
                logger.debug("Skipping event without document_id")
                return

            event_type = None
            event_data = {}

            # CREATE
            if op == "c":
                event_type = "document.created"
                event_data = {
                    "id": after.get("id"),
                    "title": after.get("title"),
                    "status": after.get("status"),
                    "created_by": after.get("created_by"),
                    "created_at": after.get("created_at"),
                }

            # UPDATE
            elif op == "u":
                changes = self._detect_changes(before, after)

                if "status" in changes:
                    old_status, new_status = changes["status"]

                    event_type = "document.status_changed"
                    event_data = {
                        "id": after.get("id"),
                        "title": after.get("title"),
                        "old_status": old_status,
                        "new_status": new_status,
                        "version": after.get("version"),
                    }

                    # Specific events for important statuses
                    if new_status == "signed":
                        event_type = "document.signed"
                    elif new_status == "viewed":
                        event_type = "document.viewed"
                    elif new_status == "sent":
                        event_type = "document.sent"

                elif "title" in changes:
                    event_type = "document.updated"
                    event_data = {
                        "id": after.get("id"),
                        "title": after.get("title"),
                        "version": after.get("version"),
                    }

            # DELETE
            elif op == "d":
                event_type = "document.deleted"
                event_data = {
                    "id": before.get("id"),
                    "title": before.get("title")
                }

            # Broadcast if we have an event
            if event_type:
                message = {
                    "type": event_type,
                    "data": event_data,
                    "timestamp": value.get("source", {}).get("ts_ms"),
                }

                await manager.broadcast_to_document(document_id, message)

                logger.info(
                    f"Broadcasted '{event_type}' for document {document_id} "
                    f"to {manager.get_connection_count(document_id)} client(s)"
                )

        except Exception as e:
            logger.exception(f"Error processing document event: {e}")

    async def _process_signature_event(self, value: dict[str, Any]):
        """Process signature CDC event and broadcast to WebSocket clients."""
        try:
            op = value.get("op")
            after = value.get("after", {})

            if op == "c":
                document_id = after.get("document_id")

                if document_id:
                    message = {
                        "type": "signature.added",
                        "data": {
                            "signature_id": after.get("id"),
                            "document_id": document_id,
                            "signer_name": after.get("signer_name"),
                            "signer_email": after.get("signer_email"),
                            "signed_at": after.get("signed_at"),
                        },
                        "timestamp": value.get("source", {}).get("ts_ms"),
                    }

                    await manager.broadcast_to_document(document_id, message)

                    logger.info(
                        f"Broadcasted 'signature.added' for document {document_id} "
                        f"to {manager.get_connection_count(document_id)} client(s)"
                    )

        except Exception as e:
            logger.error(f"Error processing signature event: {e}", exc_info=True)

    def _detect_changes(self, before: dict, after: dict) -> dict[str, tuple]:
        """Detect what fields changed between before and after."""
        if not before:
            return {}

        changes = {}
        for key in ["status", "title", "version"]:
            old_value = before.get(key)
            new_value = after.get(key)
            if old_value != new_value:
                changes[key] = (old_value, new_value)

        return changes

    async def stop(self):
        """Stop Kafka consumer gracefully."""
        logger.info("Stopping Kafka consumer...")

        self.running = False

        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass

        if self.consumer:
            await self.consumer.stop()

        logger.info("Kafka consumer stopped")


kafka_consumer = WebSocketKafkaConsumer()
