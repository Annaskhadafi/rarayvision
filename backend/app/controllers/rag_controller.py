import logging
from typing import Optional, List, Dict, Any
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
    top_k: int = 5
    document_id: Optional[str] = None
    enable_rerank: bool = True


class ChatRequest(BaseModel):
    query: str
    messages: Optional[List[Dict[str, Any]]] = None # Multi-turn conversation history
    session_id: Optional[str] = None # Redis session ID for persistent memory
    top_k: int = 5
    document_id: Optional[str] = None
    system_prompt: Optional[str] = None
    enable_rerank: bool = True


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Optional[int] = None # 1 for thumbs up, -1 for thumbs down
    feedback_notes: Optional[str] = None
    correction_text: Optional[str] = None


class LearnFactRequest(BaseModel):
    content: str
    subject: Optional[str] = None
    fact_type: str = "learned_knowledge"


class BulkDeleteFactsRequest(BaseModel):
    fact_ids: List[str]


@router.get("/info", summary="Get RAG & Embedding Engine Info")
def get_rag_info():
    """Returns active embedding provider (FastEmbed local ONNX, Gemini, etc.) and vector dimensions."""
    return {
        "status": "success",
        "data": RagService.get_embedding_info()
    }


from starlette.concurrency import run_in_threadpool


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
    Executed in thread pool to prevent blocking the async event loop.
    """
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        result = await run_in_threadpool(
            RagService.ingest_document,
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
async def search_knowledge(
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

    results = await run_in_threadpool(
        RagService.search_similar_chunks,
        db=db,
        query=req.query,
        top_k=req.top_k,
        document_id=req.document_id,
        enable_rerank=req.enable_rerank
    )

    return {
        "status": "success",
        "query": req.query,
        "results_count": len(results),
        "results": results
    }


@router.post("/chat", summary="RAG Chatbot Endpoint (Retrieve Context + Generate Answer)")
async def rag_chat(
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

    chat_res = await run_in_threadpool(
        RagService.chat_completion,
        db=db,
        query=req.query,
        messages=req.messages,
        session_id=req.session_id,
        top_k=req.top_k,
        document_id=req.document_id,
        custom_system_prompt=req.system_prompt,
        user_id=current_user.id if current_user else None,
        enable_rerank=req.enable_rerank
    )

    return {
        "status": "success",
        "data": chat_res
    }


@router.post("/feedback", summary="Submit Message Feedback & Corrections (Self-Growth Engine)")
async def submit_message_feedback(
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Records user feedback (thumbs up/down) and applies Self-Growth:
    If a correction text is provided, it is automatically vectorized and saved
    into long-term memory for future RAG queries.
    """
    try:
        res = await run_in_threadpool(
            RagService.submit_feedback,
            db=db,
            message_id=req.message_id,
            rating=req.rating,
            feedback_notes=req.feedback_notes,
            correction_text=req.correction_text,
            user_id=current_user.id if current_user else None
        )
        return {"status": "success", "data": res}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"[RagController] submit_feedback error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/learn", summary="Directly Teach AI a New Fact or Rule (Self-Growth)")
async def teach_fact(
    req: LearnFactRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Adds a verified fact, domain rule, or glossary entry directly to RAG long-term memory.
    """
    try:
        res = await run_in_threadpool(
            RagService.learn_fact,
            db=db,
            content=req.content,
            subject=req.subject,
            fact_type=req.fact_type,
            user_id=current_user.id if current_user else None,
            learned_from="direct_input"
        )
        return {"status": "success", "data": res}
    except Exception as e:
        logger.error(f"[RagController] teach_fact error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/facts", summary="List All Learned Long-Term Memory Facts")
async def get_learned_facts(
    limit: int = Query(100, ge=1, le=500),
    fact_type: Optional[str] = Query(None, description="Filter by fact_type: auto_chat, user_correction, learned_knowledge"),
    learned_from: Optional[str] = Query(None, description="Filter by learned_from: auto_chat, user_feedback, direct_input"),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Retrieves active learned facts from PostgreSQL long-term memory, with optional filters."""
    facts = await run_in_threadpool(
        RagService.get_learned_facts,
        db=db,
        user_id=current_user.id if current_user else None,
        limit=limit,
        fact_type=fact_type,
        learned_from=learned_from
    )
    return {"status": "success", "total": len(facts), "data": facts}


@router.delete("/memory/facts/{fact_id}", summary="Delete or Deactivate a Learned Fact")
async def delete_fact(
    fact_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Deletes a learned fact from memory."""
    success = await run_in_threadpool(RagService.delete_learned_fact, db=db, fact_id=fact_id)
    if not success:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "success", "message": "Fact deleted"}


@router.post("/memory/facts/bulk-delete", summary="Bulk Delete Multiple Learned Facts")
async def bulk_delete_facts(
    req: BulkDeleteFactsRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Bulk-deletes multiple learned facts by ID array."""
    try:
        deleted_count = await run_in_threadpool(
            RagService.delete_learned_facts_bulk,
            db=db,
            fact_ids=req.fact_ids
        )
        return {"status": "success", "deleted": deleted_count}
    except Exception as e:
        logger.error(f"[RagController] bulk_delete_facts error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/cleanup", summary="Manually Trigger Old Chat Session Cleanup")
async def cleanup_old_sessions(
    days: int = Query(7, ge=1, le=365, description="Delete sessions older than N days"),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Manually triggers cleanup of chat sessions older than `days` days.
    Also removes associated auto_chat memory facts from those sessions.
    The daily auto-cleanup already runs every 24 hours automatically.
    """
    try:
        result = await run_in_threadpool(
            RagService.cleanup_old_chat_sessions,
            db=db,
            days=days
        )
        return {
            "status": "success",
            "message": f"Cleanup selesai: sesi > {days} hari dihapus.",
            "data": result
        }
    except Exception as e:
        logger.error(f"[RagController] cleanup_old_sessions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", summary="List Persistent Conversation Sessions")
async def list_sessions(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Returns persistent conversation sessions stored in PostgreSQL."""
    sessions = await run_in_threadpool(
        RagService.get_user_sessions,
        db=db,
        user_id=current_user.id if current_user else None,
        limit=limit
    )
    return {"status": "success", "total": len(sessions), "data": sessions}


@router.get("/sessions/{session_id}/messages", summary="Get Full Messages of a Session from DB")
async def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Returns persistent message history for a session from PostgreSQL."""
    messages = await run_in_threadpool(RagService.get_session_messages, db=db, session_id=session_id)
    return {"status": "success", "session_id": session_id, "data": messages}


@router.delete("/sessions/{session_id}", summary="Delete Conversation Session")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    """Deletes a session from PostgreSQL and Redis."""
    from ..services.redis_service import RedisService
    RedisService.clear_chat_history(session_id)
    success = await run_in_threadpool(RagService.delete_session, db=db, session_id=session_id)
    return {"status": "success" if success else "not_found"}


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
    RagService._invalidate_chunk_cache()

    return {
        "status": "success",
        "message": f"Document '{doc.filename}' and its chunks were deleted successfully."
    }
