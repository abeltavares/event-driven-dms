# app/main.py (FIXED)

import asyncio
import logging
from contextlib import asynccontextmanager
from json import JSONDecodeError

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .auth import jwt_auth
from .config import get_settings
from .connection_manager import manager
from .kafka_consumer import kafka_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    logger.info(f"{settings.service_name} starting up...")

    # Start Kafka consumer
    await kafka_consumer.start()

    logger.info(f"{settings.service_name} started successfully")
    logger.info("   WebSocket: ws://0.0.0.0:8000/ws/{document_id}?token=YOUR_TOKEN")

    yield

    logger.info(f"{settings.service_name} shutting down...")

    # Stop Kafka consumer
    await kafka_consumer.stop()

    logger.info(f"{settings.service_name} shutdown complete")


app = FastAPI(
    title="WebSocket Service",
    description="Real-time document updates via WebSocket",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health/live")
async def liveness():
    """Liveness probe."""
    return {"status": "alive", "service": settings.service_name}


@app.get("/health/ready")
async def readiness():
    """Readiness probe."""
    return {
        "status": "ready",
        "service": settings.service_name,
        "kafka_consumer": "running" if kafka_consumer.running else "stopped",
        "total_connections": manager.get_total_connections(),
    }


@app.get("/stats")
async def get_stats():
    """Get WebSocket statistics."""
    return {
        "total_connections": manager.get_total_connections(),
        "documents_with_subscribers": len(manager.active_connections),
        "kafka_consumer_running": kafka_consumer.running,
    }


@app.get("/auth/token")
async def create_test_token(
    user_id: str = Query(..., description="User ID"),
    email: str = Query(..., description="User email"),
):
    """Create JWT token for testing."""
    token = jwt_auth.create_token(user_id, email)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "email": email,
    }


@app.websocket("/ws/{document_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    document_id: str,
    token: str | None = Query(None, description="JWT token"),
):
    """
    WebSocket endpoint for real-time document updates.

    Usage:
        ws://localhost:8004/ws/{document_id}?token=YOUR_JWT_TOKEN

    Events sent to client:
        - document.created
        - document.status_changed
        - document.signed
        - document.viewed
        - document.sent
        - document.deleted
        - signature.added
    """
    # Authenticate
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        logger.warning("WebSocket connection rejected: missing token")
        return

    user_info = jwt_auth.verify_token(token)
    if not user_info:
        await websocket.close(code=1008, reason="Invalid token")
        logger.warning("WebSocket connection rejected: invalid token")
        return

    await manager.connect(websocket, document_id, user_info)

    await manager.send_to_user(
        websocket,
        {
            "type": "connection.established",
            "data": {
                "document_id": document_id,
                "user_id": user_info.get("sub"),
                "email": user_info.get("email"),
                "message": f"Connected to document {document_id}",
            },
        },
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except JSONDecodeError:
                logger.warning("Received invalid JSON from client")
                await manager.send_to_user(
                    websocket,
                    {"type": "error", "message": "Invalid JSON"}
                )
                continue

            # Handle ping/pong
            if data.get("type") == "ping":
                await manager.send_to_user(
                    websocket,
                    {"type": "pong", "timestamp": data.get("timestamp")}
                )

            # Handle subscription changes
            elif data.get("type") == "subscribe":
                new_document_id = data.get("document_id")
                if new_document_id:
                    logger.info(
                        f"Client {user_info.get('email')} wants to subscribe to {new_document_id}"
                    )
                    # Note: Current implementation supports one document per connection

            # Echo other messages (for debugging)
            else:
                logger.debug(f"Received from client: {data}")

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info(f"Client {user_info.get('email')} disconnected normally")

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await manager.disconnect(websocket)


@app.post("/broadcast/{document_id}")
async def manual_broadcast(document_id: str, message: dict):
    """Manual broadcast endpoint (for testing)."""
    await manager.broadcast_to_document(document_id, message)

    return {
        "status": "broadcasted",
        "document_id": document_id,
        "recipients": manager.get_connection_count(document_id),
    }
