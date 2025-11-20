# app/main.py (FIXED)

import logging
from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, FastAPI, HTTPException, Query

from .config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


async def get_es_client() -> AsyncElasticsearch:
    """Dependency to get Elasticsearch client."""
    if not hasattr(app.state, "es_client"):
        raise HTTPException(
            status_code=503,
            detail="Elasticsearch client not initialized"
        )
    return app.state.es_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Search Service starting...")

    app.state.es_client = AsyncElasticsearch(
        hosts=[settings.elasticsearch_url],
        request_timeout=30
    )

    try:
        info = await app.state.es_client.info()
        logger.info(f"Connected to Elasticsearch {info['version']['number']}")
    except Exception as e:
        logger.error(f"Failed to connect to Elasticsearch: {e}")
        raise

    yield

    await app.state.es_client.close()
    logger.info("Search Service shutdown complete")


app = FastAPI(
    title="Search Service",
    description="Read-only search API for documents",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health/live")
async def liveness():
    """Liveness probe."""
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness(es: AsyncElasticsearch = Depends(get_es_client)):
    """Readiness probe - checks Elasticsearch connection."""
    try:
        info = await es.info()
        return {"status": "ready", "elasticsearch": info["version"]["number"]}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Elasticsearch unavailable") from e


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    status: str | None = Query(None, description="Filter by status"),
    created_by: str | None = Query(None, description="Filter by creator"),
    from_: int = Query(0, ge=0, alias="from", description="Offset"),
    size: int = Query(10, ge=1, le=100, description="Number of results"),
    es: AsyncElasticsearch = Depends(get_es_client)
):
    """
    Search documents with filters.
    
    Example: GET /search?q=contract&status=signed&from=0&size=10
    """
    try:
        must_clauses = [
            {
                "multi_match": {
                    "query": q,
                    "fields": ["title^2", "created_by"],  # ← Fixed
                    "fuzziness": "AUTO",
                }
            }
        ]

        filter_clauses = []
        if status:
            filter_clauses.append({"term": {"status": status}})
        if created_by:
            filter_clauses.append({"term": {"created_by.keyword": created_by}})

        search_body = {
            "query": {"bool": {"must": must_clauses, "filter": filter_clauses}},
            "from": from_,
            "size": size,
            "highlight": {
                "fields": {
                    "title": {}
                }
            },
            "sort": [
                {"_score": {"order": "desc"}},
                {"created_at": {"order": "desc"}}
            ],
        }

        response = await es.search(
            index=settings.elasticsearch_index,
            body=search_body
        )

        hits = response["hits"]
        return {
            "total": hits["total"]["value"],
            "documents": [
                {
                    **hit["_source"],
                    "score": hit["_score"],
                    "highlights": hit.get("highlight", {}),
                }
                for hit in hits["hits"]
            ],
            "took_ms": response["took"],
            "from": from_,
            "size": size,
        }

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from e


@app.get("/suggest")
async def suggest(
    q: str = Query(..., min_length=2, description="Prefix to autocomplete"),
    size: int = Query(5, ge=1, le=20, description="Number of suggestions"),
    es: AsyncElasticsearch = Depends(get_es_client)
):
    """
    Autocomplete suggestions using prefix query.
    
    Example: GET /suggest?q=contr&size=5
    """
    try:
        search_body = {
            "query": {
                "prefix": {
                    "title.keyword": {
                        "value": q,
                        "case_insensitive": True
                    }
                }
            },
            "size": size,
            "_source": ["title"]
        }

        response = await es.search(
            index=settings.elasticsearch_index,
            body=search_body
        )

        suggestions = [
            hit["_source"]["title"]
            for hit in response["hits"]["hits"]
        ]

        return {"suggestions": suggestions}

    except Exception as e:
        logger.error(f"Suggest error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Suggestion failed") from e


@app.get("/aggregations/{field}")
async def aggregations(
    field: str,
    q: str | None = Query(None, description="Optional search query"),
    es: AsyncElasticsearch = Depends(get_es_client)
):
    """
    Get faceted counts for a field.
    
    Example: GET /aggregations/status?q=contract
    """
    try:
        allowed_fields = ["status", "content_type", "created_by"]
        if field not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Field must be one of: {allowed_fields}"
            )

        agg_body = {
            "size": 0,
            "aggs": {
                f"{field}_counts": {
                    "terms": {
                        "field": field if field in ["status", "content_type"] else f"{field}.keyword",
                        "size": 50,
                    }
                }
            },
        }

        if q:
            agg_body["query"] = {
                "multi_match": {
                    "query": q,
                    "fields": ["title", "created_by"]
                }
            }

        response = await es.search(
            index=settings.elasticsearch_index,
            body=agg_body
        )

        buckets = response["aggregations"][f"{field}_counts"]["buckets"]

        return {
            "field": field,
            "values": [
                {"key": bucket["key"], "count": bucket["doc_count"]}
                for bucket in buckets
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Aggregation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Aggregation failed") from e
