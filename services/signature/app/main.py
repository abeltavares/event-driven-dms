# app/main.py (FIXED)

import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import Base, engine, get_db
from .grpc_client import grpc_client
from .models import Signature
from .schemas import SignatureCreate, SignatureResponse
from .storage import storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.service_name} starting...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await storage.ensure_bucket()
    await grpc_client.connect()

    logger.info(f"{settings.service_name} started")

    yield

    logger.info(f"{settings.service_name} shutting down...")
    await grpc_client.disconnect()
    await engine.dispose()
    logger.info(f"{settings.service_name} stopped")


app = FastAPI(
    title="Signature Service",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health/live")
async def liveness():
    """Liveness probe."""
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)):
    """Readiness probe - checks dependencies."""
    try:
        await db.execute(select(1))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")


@app.post("/signatures", response_model=SignatureResponse, status_code=201)
async def create_signature(
    signature: SignatureCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Create signature with async S3 upload and gRPC status update."""
    # Validate document exists via gRPC
    exists = await grpc_client.document_exists(str(signature.document_id))
    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"Document {signature.document_id} not found"
        )

    # Get client IP
    client_ip = signature.ip_address or request.client.host

    # Create signature record
    db_signature = Signature(
        document_id=signature.document_id,
        signer_email=signature.signer_email,
        signer_name=signature.signer_name,
        signature_data=signature.signature_data,
        ip_address=client_ip,
    )

    db.add(db_signature)
    await db.flush()

    # Upload signature image to S3 if provided
    if signature.signature_data:
        await storage.upload_signature(
            str(db_signature.id),
            signature.signature_data.encode("utf-8")
        )

    await db.commit()
    await db.refresh(db_signature)

    background_tasks.add_task(
        update_document_status_grpc,
        str(signature.document_id)
    )

    logger.info(f"Signature created: {db_signature.id} for document {signature.document_id}")
    return db_signature


async def update_document_status_grpc(document_id: str):
    """Update document status to 'signed' via gRPC."""
    try:
        response = await grpc_client.update_document_status(
            document_id=document_id,
            status="signed"
        )

        if response:
            logger.info(
                f"Document {document_id} updated to 'signed' (v{response.version})"
            )
        else:
            logger.error(f"Failed to update document {document_id} status")

    except Exception as e:
        logger.error(f"Error updating document status: {e}", exc_info=True)


@app.get("/signatures", response_model=list[SignatureResponse])
async def list_signatures(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all signatures with pagination."""
    result = await db.execute(
        select(Signature)
        .order_by(Signature.signed_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@app.get("/documents/{document_id}/signatures", response_model=list[SignatureResponse])
async def get_document_signatures(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all signatures for a specific document."""
    result = await db.execute(
        select(Signature)
        .where(Signature.document_id == document_id)
        .order_by(Signature.signed_at.asc())
    )
    signatures = result.scalars().all()

    if not signatures:
        raise HTTPException(
            status_code=404,
            detail=f"No signatures found for document {document_id}"
        )

    return signatures


@app.get("/signatures/{signature_id}", response_model=SignatureResponse)
async def get_signature(
    signature_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get signature by ID."""
    result = await db.execute(
        select(Signature).where(Signature.id == signature_id)
    )
    signature = result.scalar_one_or_none()

    if not signature:
        raise HTTPException(
            status_code=404,
            detail=f"Signature {signature_id} not found"
        )

    return signature
