import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections.

    Features:
    - Track connections per document
    - Broadcast messages to subscribers
    - Handle disconnections gracefully
    """

    def __init__(self):
        # document_id -> set of WebSocket connections
        self.active_connections: dict[str, set[WebSocket]] = {}

        # websocket -> user_info mapping
        self.connection_info: dict[WebSocket, dict] = {}

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, document_id: str, user_info: dict):
        """Accept WebSocket connection and subscribe to document.

        Args:
            websocket: WebSocket connection
            document_id: Document to subscribe to
            user_info: User information from JWT
        """
        await websocket.accept()

        async with self._lock:
            # Add to document subscribers
            if document_id not in self.active_connections:
                self.active_connections[document_id] = set()

            self.active_connections[document_id].add(websocket)

            # Store user info
            self.connection_info[websocket] = {
                "document_id": document_id,
                "user_id": user_info.get("sub"),
                "email": user_info.get("email"),
            }

        logger.info(
            f"WebSocket connected: {user_info.get('email')} "
            f"subscribed to document {document_id}"
        )
        logger.info(
            f"Active connections for {document_id}: {len(self.active_connections[document_id])}"
        )

    async def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        async with self._lock:
            # Get connection info
            info = self.connection_info.pop(websocket, {})
            document_id = info.get("document_id")

            if document_id and document_id in self.active_connections:
                self.active_connections[document_id].discard(websocket)

                # Clean up empty sets
                if not self.active_connections[document_id]:
                    del self.active_connections[document_id]

        logger.info(
            f"WebSocket disconnected: {info.get('email')} from document {document_id}"
        )

    async def broadcast_to_document(self, document_id: str, message: dict):
        """Broadcast message to all subscribers of a document.

        Args:
            document_id: Document ID
            message: JSON-serializable message
        """
        if document_id not in self.active_connections:
            logger.debug(f"No active connections for document {document_id}")
            return

        connections = self.active_connections[document_id].copy()

        logger.info(
            f"Broadcasting to {len(connections)} clients "
            f"for document {document_id}: {message.get('type')}"
        )

        # Send to all connections (concurrent)
        disconnected = []

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
                disconnected.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def send_to_user(self, websocket: WebSocket, message: dict):
        """Send message to specific WebSocket connection."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending to user: {e}")
            await self.disconnect(websocket)

    def get_connection_count(self, document_id: str) -> int:
        """Get number of active connections for a document."""
        return len(self.active_connections.get(document_id, set()))

    def get_total_connections(self) -> int:
        """Get total number of active connections."""
        return len(self.connection_info)


manager = ConnectionManager()
