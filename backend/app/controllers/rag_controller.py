import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.app.core.deps import get_current_user
from backend.app.database.database import get_db
from backend.app.database import models as db_models
from backend.app.database.rag_models import RagDocument, RagDocumentChunk
from backend.app.services.rag_service import RagService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["RAG Knowledge Base & pgvector"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 4
    document_id: Optional[str] = None


class ChatRequest(BaseModel):
    query: str
    messages: Optional[List[Dict[str, Any]]] = None # Multi-turn conversation history
    session_id: Optional[str] = None # Redis session ID for persistent memory
    top_k: int = 4
    document_id: Optional[str] = None
    system_prompt: Optional[str] = None


@router.get("/info", summary="Get RAG & Embedding Engine Info")
def get_rag_info():
    """Returns active embedding provider (FastEmbed local ONNX, Gemini, etc.) and vector dimensions."""
    return {
        "status": "success",
        "data": RagService.get_embedding_info()
    }


@router.post("/ingest", summary="Ingest Document to Knowledge Base & pgvector")
async def ingest_document(
    file: UploadFile = File(..., description="Document file (DOCX, PDF, XLSX, PPTX, CSV, EPUB, Images)"),
    auto_ocr: bool = Form(True, description="Enable RapidOCR fallback for scanned PDF pages"),
    force_ocr: bool = Form(False, description="Force full OCR across all pages"),
    format_override: Optional[str] = Form(None, description="Explicit format override"),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Complete RAG Knowledge Base Ingestion:
    1. Converts document to structured Markdown via AnyDoc.
    2. Persists file to S3 Object Storage.
    3. Splits Markdown into semantic chunk blocks.
    4. Generates vector embeddings via FastEmbed ONNX (100% free offline).
    5. Saves into PostgreSQL pgvector table for real-time similarity search.
    """
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        result = RagService.ingest_document(
            db=db,
            file_bytes=file_bytes,
            filename=file.filename or "document",
            auto_ocr=auto_ocr,
            force_ocr=force_ocr,
            format_override=format_override
        )
        return result

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[RagController] ingest_document error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to ingest document: {str(e)}")


@router.post("/search", summary="Semantic Vector Search (pgvector Cosine Distance)")
def search_knowledge(
    req: SearchRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Performs cosine similarity search against pgvector embeddings,
    returning the most relevant Markdown chunks with similarity scores.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Search query cannot be empty")

    results = RagService.search_similar_chunks(
        db=db,
        query=req.query,
        top_k=req.top_k,
        document_id=req.document_id
    )

    return {
        "status": "success",
        "query": req.query,
        "results_count": len(results),
        "results": results
    }


@router.post("/chat", summary="RAG Chatbot Endpoint (Retrieve Context + Generate Answer)")
def rag_chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Full RAG Chatbot generation:
    1. Vector search retrieves top-k relevant Markdown chunks from pgvector.
    2. Context is compiled with document citations.
    3. LLM generates grounded answers.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    chat_res = RagService.chat_completion(
        db=db,
        query=req.query,
        messages=req.messages,
        session_id=req.session_id,
        top_k=req.top_k,
        document_id=req.document_id,
        custom_system_prompt=req.system_prompt
    )

    return {
        "status": "success",
        "data": chat_res
    }


@router.get("/redis/status", summary="Get Redis Status & Latency")
def get_redis_status():
    """Returns Redis connection status, ping latency, and memory statistics."""
    from ..services.redis_service import RedisService
    return {
        "status": "success",
        "data": RedisService.get_status()
    }


@router.get("/chat/session/{session_id}/history", summary="Get Chat Session History from Redis")
def get_session_history(session_id: str, limit: int = Query(10, ge=1, le=50)):
    """Retrieves persistent chat history for a session from Redis."""
    from ..services.redis_service import RedisService
    history = RedisService.get_chat_history(session_id, limit=limit)
    return {
        "status": "success",
        "session_id": session_id,
        "history": history
    }


@router.delete("/chat/session/{session_id}", summary="Clear Chat Session History from Redis")
def clear_session_history(session_id: str):
    """Deletes conversation memory for a session in Redis."""
    from ..services.redis_service import RedisService
    success = RedisService.clear_chat_history(session_id)
    return {
        "status": "success" if success else "not_found",
        "message": f"Session '{session_id}' chat history cleared."
    }


@router.get("/documents", summary="List All Documents in Knowledge Base")
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Returns all ingested documents, total chunk counts, S3 links, and statistics."""
    total_docs = db.query(RagDocument).count()
    total_chunks = db.query(RagDocumentChunk).count()

    docs = db.query(RagDocument).order_by(RagDocument.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "status": "success",
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "format": d.format,
                "s3_url": d.s3_url,
                "local_url": d.local_url,
                "char_count": d.char_count,
                "word_count": d.word_count,
                "total_chunks": d.total_chunks,
                "engine_used": d.engine_used,
                "embedding_model": d.embedding_model,
                "created_at": d.created_at.isoformat() if d.created_at else None
            }
            for d in docs
        ]
    }


@router.get("/documents/{document_id}/chunks", summary="Get Chunks of a Specific Document")
def get_document_chunks(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Retrieves all individual Markdown chunks for a given document."""
    doc = db.query(RagDocument).filter(RagDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = db.query(RagDocumentChunk).filter(RagDocumentChunk.document_id == document_id).order_by(RagDocumentChunk.chunk_index.asc()).all()

    return {
        "status": "success",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "format": doc.format,
            "s3_url": doc.s3_url,
            "total_chunks": doc.total_chunks
        },
        "chunks": [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "heading": c.heading,
                "content": c.content,
                "token_count": c.token_count,
                "has_embedding": c.embedding is not None
            }
            for c in chunks
        ]
    }


@router.delete("/documents/{document_id}", summary="Delete Document from Knowledge Base & pgvector")
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Deletes document record and cascades removal of all associated pgvector chunk embeddings."""
    doc = db.query(RagDocument).filter(RagDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()

    return {
        "status": "success",
        "message": f"Document '{doc.filename}' and its chunks were deleted successfully."
    }
