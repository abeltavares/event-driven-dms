# services/document/app/main.py

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import UUID
from uuid_extensions import uuid7

from fastapi import Depends, FastAPI, HTTPException, Request  # ✅ Add Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .cache import cache
from .analytics import analytics
from .config import get_settings
from .database import Base, engine, get_db
from .grpc_server import serve_grpc
from .models import Document, DocumentStatus
from .schemas import DocumentCreate, DocumentResponse, DocumentUpdate
from .storage import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.service_name} starting...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await cache.connect()
    await analytics.connect() 
    await storage.ensure_buckets()

    grpc_task = asyncio.create_task(serve_grpc())

    logger.info(f"{settings.service_name} started - HTTP: 8000, gRPC: 50051")

    yield

    grpc_task.cancel()
    try:
        await grpc_task
    except asyncio.CancelledError:
        pass

    await cache.disconnect()
    await analytics.disconnect()
    await engine.dispose()


app = FastAPI(title="Document Service", version="1.0.0", lifespan=lifespan)


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(1))
        await cache.redis.ping()
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")


@app.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(document: DocumentCreate, db: AsyncSession = Depends(get_db)):
    """Create document with async S3 upload."""
    document_id = uuid7()
    content_bytes = document.content.encode("utf-8")

    s3_key = await storage.upload_document(str(document_id), content_bytes)

    db_document = Document(
        id=document_id,
        title=document.title,
        content_type=document.content_type,
        content_size=len(content_bytes),
        s3_key=s3_key,
        created_by=document.created_by,
        status=DocumentStatus.CREATED.value,
    )

    db.add(db_document)
    await db.commit()
    await db.refresh(db_document)

    await cache.set(
        f"document:{document_id}",
        DocumentResponse.from_orm(db_document).dict(),
        ttl=settings.redis_cache_ttl
    )

    logger.info(f"Document created: {document_id}")
    return db_document


@app.get("/documents", response_model=list[DocumentResponse])
async def list_documents(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """List documents with pagination."""
    result = await db.execute(
        select(Document).offset(skip).limit(limit).order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get document with cache and analytics tracking."""
    
    # Check cache first
    cached = await cache.get(f"document:{document_id}")
    if cached:
        logger.info(f"Cache hit: {document_id}")
        client_ip = request.client.host if request.client else "unknown"
        await analytics.track_view(str(document_id), client_ip)
        return DocumentResponse(**cached)

    # Cache miss - get from database
    logger.info(f"Cache miss: {document_id}")
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    client_ip = request.client.host if request.client else "unknown"
    await cache.incr(f"views:{document_id}")
    await cache.pfadd(f"unique_views:{document_id}", client_ip)

    # Cache the document
    await cache.set(
        f"document:{document_id}",
        DocumentResponse.from_orm(document).dict(),
        ttl=settings.redis_cache_ttl
    )

    return document


@app.patch("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID, update: DocumentUpdate, db: AsyncSession = Depends(get_db)
):
    """Update document with optimistic locking."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(document, field, value)

    document.version += 1

    await db.commit()
    await db.refresh(document)

    await cache.delete(f"document:{document_id}")

    logger.info(f"Document updated: {document_id} v{document.version}")
    return document


@app.get("/documents/{document_id}/stats")
async def get_document_stats(document_id: UUID):
    stats = await analytics.get_stats(str(document_id))
    return {
        "document_id": str(document_id),
        **stats
    }
