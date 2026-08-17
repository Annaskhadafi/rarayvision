import os
import re
import uuid
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

try:
    from app.database.rag_models import (
        RagDocument, RagDocumentChunk,
        RagChatSession, RagChatMessage, RagMemoryFact
    )
    from app.services.anydoc_service import AnyDocService
    from app.services.redis_service import RedisService
except ImportError:
    from backend.app.database.rag_models import (
        RagDocument, RagDocumentChunk,
        RagChatSession, RagChatMessage, RagMemoryFact
    )
    from backend.app.services.anydoc_service import AnyDocService
    from backend.app.services.redis_service import RedisService

logger = logging.getLogger(__name__)

# Lazy singleton for FastEmbed ONNX
_fastembed_instance = None


def get_fastembed_model():
    global _fastembed_instance
    if _fastembed_instance is None:
        try:
            from fastembed import TextEmbedding
            # BAAI/bge-small-en-v1.5 is fast (384-d), free, lightweight (~130MB), high MTEB score
            _fastembed_instance = TextEmbedding("BAAI/bge-small-en-v1.5")
            logger.info("[RagService] FastEmbed ONNX local embedding engine initialized (384-d).")
        except Exception as e:
            logger.error(f"[RagService] Failed to load FastEmbed: {e}")
            _fastembed_instance = False
    return _fastembed_instance


# Domain Bilingual Query Expansion Dictionary (Indonesian -> Technical Engineering / Tire Standards)
DOMAIN_SYNONYMS = {
    "tekanan": ["pressure", "inflation", "operating pressure", "bar", "psi", "cold pressure"],
    "angin": ["pressure", "inflation", "psi", "bar"],
    "ban": ["tire", "tyre", "earthmover", "otr", "tubeless"],
    "muatan": ["load", "payload", "capacity", "kg", "lbs", "load index"],
    "beban": ["load", "payload", "capacity", "kg", "lbs", "load index"],
    "kapasitas": ["capacity", "payload", "load"],
    "kecepatan": ["speed", "km/h", "mph", "speed symbol"],
    "ukuran": ["size", "dimension", "radial", "rim", "diameter"],
    "dimensi": ["dimension", "size", "width", "diameter", "overall diameter"],
    "tapak": ["tread", "tread depth", "otd", "pattern"],
    "alur": ["tread", "tread depth", "otd", "groove"],
    "kembangan": ["tread", "pattern", "otd"],
    "kedalaman": ["depth", "tread depth", "otd", "mm", "32nds"],
    "panas": ["tkph", "tmph", "temperature", "heat"],
    "suhu": ["temperature", "tkph", "tmph", "heat"],
    "berat": ["weight", "kg", "lbs", "mass"],
    "velg": ["rim", "wheel", "flange"],
    "pelek": ["rim", "wheel", "flange"],
    "tipe": ["type", "pattern", "star rating", "code"],
    "aturan": ["sop", "procedure", "rule", "instruction"],
    "dongkrak": ["hydraulic jack", "jack", "lifting"],
    "bongkar": ["demounting", "removal", "disassembly"],
    "pasang": ["mounting", "assembly", "installation"]
}


def expand_bilingual_query(query: str) -> str:
    """Expands Indonesian technical query terms with English technical synonyms for enhanced RAG cross-lingual recall."""
    if not query:
        return ""
    q_clean = query.lower()
    words = re.findall(r'[a-zA-Z0-9_\-\.\/]+', q_clean)
    added_terms = []
    for w in words:
        if w in DOMAIN_SYNONYMS:
            added_terms.extend(DOMAIN_SYNONYMS[w])
    if added_terms:
        # Keep unique terms
        unique_added = list(dict.fromkeys(added_terms))
        return f"{query} {' '.join(unique_added[:8])}"
    return query


def tokenize_text(text: str) -> List[str]:
    """Tokenize alphanumeric words, technical identifiers, SKU numbers, and size codes."""
    if not text:
        return []
    clean = text.lower()
    tokens = re.findall(r'[a-zA-Z0-9_\-\.\/]+', clean)
    return [t.strip('.-_/') for t in tokens if len(t.strip('.-_/')) >= 2]


def compute_bm25_scores(query: str, items: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """
    Computes Okapi BM25 scores for document chunks against a search query.
    High-performance pure-Python SIMD-friendly lexical matching.
    """
    import numpy as np
    query_tokens = tokenize_text(query)
    if not query_tokens or not items:
        return [0.0] * len(items)

    doc_token_lists = [tokenize_text(f"{it.get('heading', '')} {it.get('content', '')}") for it in items]
    doc_lens = [len(tokens) for tokens in doc_token_lists]
    avgdl = sum(doc_lens) / max(len(doc_lens), 1)
    if avgdl == 0:
        avgdl = 1.0

    N = len(items)
    df = {}
    for q_tok in query_tokens:
        df[q_tok] = sum(1 for tokens in doc_token_lists if q_tok in tokens)

    scores = []
    for idx, tokens in enumerate(doc_token_lists):
        doc_len = doc_lens[idx]
        tf_dict = {}
        for t in tokens:
            tf_dict[t] = tf_dict.get(t, 0) + 1

        score = 0.0
        for q_tok in query_tokens:
            n_q = df.get(q_tok, 0)
            idf = max(0.0, float(np.log((N - n_q + 0.5) / (n_q + 0.5) + 1.0)))
            tf = tf_dict.get(q_tok, 0)
            if tf > 0:
                tf_norm = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / avgdl)))
                score += idf * tf_norm
        scores.append(float(score))

    return scores


class RagService:
    @staticmethod
    def get_embedding_info() -> Dict[str, Any]:
        """Returns active embedding provider, LLM engine info, and Redis status."""
        groq_key = os.getenv("GROQ_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

        active_llm = "Groq LPU (qwen/qwen3.6-27b)" if groq_key else "OpenRouter"

        return {
            "default_provider": "local_fastembed",
            "model_name": "BAAI/bge-small-en-v1.5",
            "vector_dimension": 384,
            "pricing": "100% Free & Offline",
            "active_llm": active_llm,
            "groq_configured": bool(groq_key),
            "gemini_configured": bool(gemini_key),
            "openrouter_configured": bool(openrouter_key),
            "vector_dimensions": 384
        }

    @classmethod
    def generate_embeddings(cls, texts: List[str]) -> List[List[float]]:
        """
        Generates vector embeddings for a list of text strings with safe batching.
        Defaults to high-speed local FastEmbed ONNX (100% free, 384-d).
        """
        if not texts:
            return []

        model = get_fastembed_model()
        if model:
            try:
                import gc
                all_embs = []
                batch_size = 32
                for i in range(0, len(texts), batch_size):
                    batch_slice = texts[i:i + batch_size]
                    gen = model.embed(batch_slice, batch_size=32)
                    for emb in gen:
                        all_embs.append([float(x) for x in emb])
                    gc.collect()
                return all_embs
            except Exception as e:
                logger.error(f"[RagService] FastEmbed generation error: {e}")

        # Fallback dummy embedding (for testing without model)
        logger.warning("[RagService] Using fallback zero-vector embeddings.")
        return [[0.0] * 384 for _ in texts]

    @classmethod
    def generate_single_embedding(cls, text: str) -> List[float]:
        """Generates embedding vector for a single query string."""
        results = cls.generate_embeddings([text])
        return results[0] if results else [0.0] * 384

    @staticmethod
    def split_markdown_into_chunks(
        markdown_text: str,
        max_chunk_chars: int = 750,
        overlap_chars: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Semantically splits Markdown text into chunks while preserving heading hierarchy,
        table structure (including column headers), and paragraph boundaries.
        """
        if not markdown_text or not markdown_text.strip():
            return []

        # Split by markdown headers
        raw_sections = re.split(r'\n(?=#{1,4}\s)', markdown_text)
        chunks = []
        hierarchy_stack = {}

        for sec in raw_sections:
            sec_str = sec.strip()
            if not sec_str:
                continue

            # Track heading level and hierarchy breadcrumb path
            header_match = re.match(r'^(#{1,4})\s+(.*)$', sec_str.splitlines()[0])
            if header_match:
                level = len(header_match.group(1))
                h_title = header_match.group(2).strip()
                hierarchy_stack[level] = h_title
                hierarchy_stack = {k: v for k, v in hierarchy_stack.items() if k <= level}

            active_headings = [hierarchy_stack[k] for k in sorted(hierarchy_stack.keys())]
            current_heading = " > ".join(active_headings) if active_headings else "General"

            # Check if section contains a markdown table header
            table_header_prefix = ""
            lines = sec_str.splitlines()
            if len(lines) >= 2 and "|" in lines[0] and ("---" in lines[1] or (len(lines) > 2 and "---" in lines[2])):
                table_header_prefix = "\n".join(lines[:2]) + "\n"

            # If section is within max_chunk_chars, keep as one chunk
            if len(sec_str) <= max_chunk_chars:
                chunks.append({
                    "content": sec_str,
                    "heading": current_heading,
                    "char_count": len(sec_str),
                    "token_estimate": len(sec_str.split())
                })
            else:
                # Split large section by paragraphs
                paragraphs = sec_str.split("\n\n")
                buf = []
                buf_len = 0

                for p in paragraphs:
                    p_clean = p.strip()
                    if not p_clean:
                        continue

                    if buf_len + len(p_clean) > max_chunk_chars and buf:
                        chunk_text = "\n\n".join(buf)
                        if table_header_prefix and not chunk_text.startswith(table_header_prefix):
                            chunk_text = f"{table_header_prefix}{chunk_text}"
                        chunks.append({
                            "content": chunk_text,
                            "heading": current_heading,
                            "char_count": len(chunk_text),
                            "token_estimate": len(chunk_text.split())
                        })
                        # Overlap: keep last paragraph
                        buf = [buf[-1]] if len(buf) > 1 else []
                        buf_len = sum(len(x) for x in buf)

                    buf.append(p_clean)
                    buf_len += len(p_clean)

                if buf:
                    chunk_text = "\n\n".join(buf)
                    if table_header_prefix and not chunk_text.startswith(table_header_prefix):
                        chunk_text = f"{table_header_prefix}{chunk_text}"
                    chunks.append({
                        "content": chunk_text,
                        "heading": current_heading,
                        "char_count": len(chunk_text),
                        "token_estimate": len(chunk_text.split())
                    })

        return chunks

    @classmethod
    def ingest_document(
        cls,
        db: Session,
        file_bytes: bytes,
        filename: str,
        auto_ocr: bool = True,
        force_ocr: bool = False,
        format_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete RAG Ingestion Pipeline:
        1. AnyDoc converts file to structured GitHub-Flavored Markdown.
        2. Auto-persists to S3 Object Storage.
        3. Splits Markdown into semantic chunk blocks with preserved headers.
        4. Vectorizes chunks via FastEmbed.
        5. Saves to PostgreSQL pgvector tables.
        """
        start_time = time.perf_counter()

        # 1. AnyDoc conversion & S3 persistence
        conv_res = AnyDocService.convert_document(
            file_bytes=file_bytes,
            filename=filename,
            auto_ocr=auto_ocr,
            force_ocr=force_ocr,
            format_override=format_override
        )

        markdown_text = conv_res.get("markdown", "")
        doc_id = str(uuid.uuid4())

        # 2. Semantic Chunking
        chunk_dicts = cls.split_markdown_into_chunks(markdown_text)
        if not chunk_dicts:
            chunk_dicts = [{
                "content": markdown_text or "Empty document",
                "heading": "Document Content",
                "char_count": len(markdown_text),
                "token_estimate": len(markdown_text.split()) if markdown_text else 0
            }]

        # 3. Generate Vector Embeddings in Batch
        chunk_texts = [c["content"] for c in chunk_dicts]
        embeddings = cls.generate_embeddings(chunk_texts)

        # 4. Save Document & Chunks in DB
        doc_record = RagDocument(
            id=doc_id,
            filename=filename,
            format=conv_res.get("format", "unknown"),
            s3_url=conv_res.get("storage", {}).get("s3_url"),
            local_url=conv_res.get("storage", {}).get("local_url"),
            char_count=conv_res.get("metrics", {}).get("characters", 0),
            word_count=conv_res.get("metrics", {}).get("words", 0),
            total_chunks=len(chunk_dicts),
            engine_used=conv_res.get("engine", "anydoc"),
            embedding_model="BAAI/bge-small-en-v1.5",
            extra_meta={
                "ocr_applied": conv_res.get("ocr_applied", False),
                "s3_stored_filename": conv_res.get("storage", {}).get("stored_filename")
            }
        )
        db.add(doc_record)

        for idx, (c_dict, emb) in enumerate(zip(chunk_dicts, embeddings)):
            chunk_record = RagDocumentChunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                chunk_index=idx,
                content=c_dict["content"],
                heading=c_dict.get("heading"),
                token_count=c_dict.get("token_estimate", 0),
                embedding=emb
            )
            db.add(chunk_record)

        db.commit()
        db.refresh(doc_record)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return {
            "status": "success",
            "document_id": doc_id,
            "filename": filename,
            "format": conv_res.get("format"),
            "s3_url": conv_res.get("storage", {}).get("s3_url"),
            "total_chunks": len(chunk_dicts),
            "char_count": conv_res.get("metrics", {}).get("characters", 0),
            "word_count": conv_res.get("metrics", {}).get("words", 0),
            "processing_time_ms": elapsed_ms,
            "embedding_model": "BAAI/bge-small-en-v1.5",
            "preview_markdown": markdown_text[:500] + ("..." if len(markdown_text) > 500 else "")
        }

    @classmethod
    def search_similar_chunks(
        cls,
        db: Session,
        query: str,
        top_k: int = 4,
        document_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes high-accuracy Hybrid Search (Dense Vector Cosine Similarity + BM25 Sparse Lexical Scoring with RRF)
        with automatic Cross-Lingual & Domain Technical Synonym Query Expansion.
        """
        expanded_query = expand_bilingual_query(query)
        query_vec = cls.generate_single_embedding(expanded_query)
        return cls._hybrid_similarity_search(db, expanded_query, query_vec, top_k, document_id, original_query=query)

    @classmethod
    def _hybrid_similarity_search(
        cls,
        db: Session,
        query: str,
        query_vec: List[float],
        top_k: int,
        document_id: Optional[str] = None,
        original_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Hybrid retrieval combining Dense Vector Cosine Similarity and BM25 Sparse Lexical Scoring
        using Reciprocal Rank Fusion (RRF).
        """
        import numpy as np

        q = db.query(RagDocumentChunk, RagDocument.filename, RagDocument.s3_url, RagDocument.format)\
              .join(RagDocument, RagDocumentChunk.document_id == RagDocument.id)
        if document_id:
            q = q.filter(RagDocumentChunk.document_id == document_id)

        rows = q.all()
        if not rows:
            return []

        q_arr = np.array(query_vec, dtype=float)
        norm_q = np.linalg.norm(q_arr)
        if norm_q == 0:
            norm_q = 1e-9

        # 1. Prepare raw items and calculate Dense Vector Cosine Similarity
        items = []
        vec_scores = []
        for chunk, fname, s3_link, fmt in rows:
            if chunk.embedding is not None:
                c_arr = np.array(chunk.embedding, dtype=float)
                norm_c = np.linalg.norm(c_arr)
                sim = float(np.dot(q_arr, c_arr) / (norm_q * norm_c)) if norm_c > 0 else 0.0
            else:
                sim = 0.0

            item = {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "filename": fname,
                "format": fmt,
                "s3_url": s3_link,
                "chunk_index": chunk.chunk_index,
                "heading": chunk.heading or "",
                "content": chunk.content or "",
                "vector_sim": max(0.0, sim)
            }
            items.append(item)
            vec_scores.append(sim)

        # 2. Calculate BM25 Sparse Lexical Scores
        bm25_scores = compute_bm25_scores(query, items)

        # 3. Rank by Vector Similarity
        vec_ranked_indices = sorted(range(len(items)), key=lambda i: vec_scores[i], reverse=True)
        vec_rank_map = {idx: rank + 1 for rank, idx in enumerate(vec_ranked_indices)}

        # 4. Rank by BM25 Score
        bm25_ranked_indices = sorted(range(len(items)), key=lambda i: bm25_scores[i], reverse=True)
        bm25_rank_map = {idx: rank + 1 for rank, idx in enumerate(bm25_ranked_indices)}

        # 5. Reciprocal Rank Fusion (RRF with k=60 constant) + Exact Keyword Boost
        q_lower = query.lower().strip()
        orig_lower = (original_query or query).lower().strip()
        scored = []
        for idx, item in enumerate(items):
            r_vec = vec_rank_map[idx]
            r_bm25 = bm25_rank_map[idx]
            rrf_score = (1.0 / (60.0 + r_vec)) + (1.0 / (60.0 + r_bm25))

            # Exact phrase match boost
            content_lower = item["content"].lower()
            heading_lower = item["heading"].lower()
            if orig_lower in heading_lower or any(w in heading_lower for w in orig_lower.split() if len(w) > 3):
                rrf_score += 0.015
            if orig_lower in content_lower:
                rrf_score += 0.010

            # Normalized score for UI presentation [0.0 - 1.0]
            norm_sim = min(1.0, (item["vector_sim"] * 0.65) + (min(1.0, bm25_scores[idx] / 5.0) * 0.35))

            scored.append({
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "filename": item["filename"],
                "format": item["format"],
                "s3_url": item["s3_url"],
                "chunk_index": item["chunk_index"],
                "heading": item["heading"],
                "content": item["content"],
                "similarity_score": round(norm_sim, 4),
                "distance": round(1.0 - norm_sim, 4),
                "rrf_score": rrf_score
            })

        # 6. Sort by RRF score descending
        scored.sort(key=lambda x: x["rrf_score"], reverse=True)
        return scored[:top_k]

    @classmethod
    def search_learned_facts(
        cls,
        db: Session,
        query: str,
        top_k: int = 3,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top learned facts/rules/corrections using vector similarity + keyword matching.
        """
        try:
            facts = db.query(RagMemoryFact).filter(RagMemoryFact.is_active == True).all()
            if not facts:
                return []

            query_vec = cls.generate_single_embedding(query)
            import numpy as np

            scored = []
            q_vec = np.array(query_vec, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)

            for f in facts:
                sim = 0.0
                if f.embedding and q_norm > 0:
                    f_vec = np.array(f.embedding, dtype=np.float32)
                    f_norm = np.linalg.norm(f_vec)
                    if f_norm > 0:
                        sim = float(np.dot(q_vec, f_vec) / (q_norm * f_norm))

                # Simple keyword overlap boost
                q_words = set(re.findall(r'\w+', query.lower()))
                f_words = set(re.findall(r'\w+', (f.content or '').lower()))
                overlap = len(q_words & f_words)
                combined_score = sim + (0.1 * min(overlap, 3))

                if combined_score > 0.45 or overlap >= 2:
                    scored.append({
                        "id": f.id,
                        "subject": f.subject,
                        "content": f.content,
                        "fact_type": f.fact_type,
                        "learned_from": f.learned_from,
                        "similarity_score": round(sim, 4),
                        "score": combined_score
                    })

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]
        except Exception as e:
            logger.warning(f"[RagService] search_learned_facts error: {e}")
            return []

    @classmethod
    def learn_fact(
        cls,
        db: Session,
        content: str,
        subject: Optional[str] = None,
        fact_type: str = "learned_knowledge",
        user_id: Optional[int] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        learned_from: str = "user_feedback"
    ) -> Dict[str, Any]:
        """
        Self-Growth Engine: Ingests a new fact, rule, or correction into long-term memory.
        Generates 384-d vector embedding and persists to PostgreSQL.
        """
        content = content.strip()
        if not content:
            raise ValueError("Konten fakta tidak boleh kosong")

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        embedding = cls.generate_single_embedding(content)

        new_fact = RagMemoryFact(
            id=fact_id,
            user_id=user_id,
            fact_type=fact_type,
            subject=subject or (content[:60] + "..." if len(content) > 60 else content),
            content=content,
            confidence_score=1.0,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            embedding=embedding,
            is_active=True,
            learned_from=learned_from
        )
        db.add(new_fact)
        db.commit()
        db.refresh(new_fact)

        logger.info(f"[RagService] Self-Growth: New fact learned [{fact_id}] ({fact_type}): {new_fact.subject}")
        return {
            "id": new_fact.id,
            "subject": new_fact.subject,
            "content": new_fact.content,
            "fact_type": new_fact.fact_type,
            "learned_from": new_fact.learned_from,
            "created_at": new_fact.created_at.isoformat() if new_fact.created_at else None
        }

    @classmethod
    def submit_feedback(
        cls,
        db: Session,
        message_id: str,
        rating: Optional[int] = None,
        feedback_notes: Optional[str] = None,
        correction_text: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Records user feedback (thumbs up/down) and applies Self-Growth if correction text is provided.
        """
        msg = db.query(RagChatMessage).filter(RagChatMessage.id == message_id).first()
        if not msg:
            raise ValueError(f"Pesan dengan ID {message_id} tidak ditemukan")

        if rating is not None:
            msg.rating = rating
        if feedback_notes:
            msg.feedback_notes = feedback_notes
        if correction_text:
            msg.correction_text = correction_text

        learned_fact = None
        # If user provided a correction or detailed feedback, ingest as learned memory
        if correction_text and len(correction_text.strip()) > 5:
            learned_fact = cls.learn_fact(
                db=db,
                content=correction_text.strip(),
                subject=f"Koreksi: {msg.content[:40]}...",
                fact_type="user_correction",
                user_id=user_id,
                source_session_id=msg.session_id,
                source_message_id=msg.id,
                learned_from="user_feedback"
            )

        db.commit()
        return {
            "message_id": msg.id,
            "rating": msg.rating,
            "feedback_notes": msg.feedback_notes,
            "correction_text": msg.correction_text,
            "learned_fact": learned_fact
        }

    @classmethod
    def save_message_to_db(
        cls,
        db: Session,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        retrieved_chunks_count: int = 0,
        latency_ms: float = 0.0,
        user_id: Optional[int] = None,
        document_id: Optional[str] = None
    ) -> RagChatMessage:
        """Persists chat turn permanently into PostgreSQL database."""
        # Find or create session
        session = db.query(RagChatSession).filter(RagChatSession.id == session_id).first()
        if not session:
            title = content[:60] if role == "user" else "Percakapan Hero Assistant"
            session = RagChatSession(
                id=session_id,
                user_id=user_id,
                title=title,
                document_id=document_id,
                is_active=True
            )
            db.add(session)
            db.commit()
        else:
            session.updated_at = datetime.utcnow()
            db.commit()

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        chat_msg = RagChatMessage(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            sources=sources or [],
            retrieved_chunks_count=retrieved_chunks_count,
            latency_ms=latency_ms
        )
        db.add(chat_msg)
        db.commit()
        db.refresh(chat_msg)
        return chat_msg

    @classmethod
    def get_user_sessions(cls, db: Session, user_id: Optional[int] = None, limit: int = 30) -> List[Dict[str, Any]]:
        """Retrieves list of persistent conversation sessions."""
        q = db.query(RagChatSession).filter(RagChatSession.is_active == True)
        if user_id:
            q = q.filter(RagChatSession.user_id == user_id)
        sessions = q.order_by(RagChatSession.updated_at.desc()).limit(limit).all()

        return [
            {
                "id": s.id,
                "title": s.title,
                "document_id": s.document_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "message_count": len(s.messages)
            }
            for s in sessions
        ]

    @classmethod
    def get_session_messages(cls, db: Session, session_id: str) -> List[Dict[str, Any]]:
        """Retrieves all messages for a specific session."""
        msgs = db.query(RagChatMessage).filter(
            RagChatMessage.session_id == session_id
        ).order_by(RagChatMessage.created_at.asc()).all()

        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sources": m.sources or [],
                "rating": m.rating,
                "feedback_notes": m.feedback_notes,
                "correction_text": m.correction_text,
                "latency_ms": m.latency_ms,
                "created_at": m.created_at.isoformat() if m.created_at else None
            }
            for m in msgs
        ]

    @classmethod
    def delete_session(cls, db: Session, session_id: str) -> bool:
        """Deletes a chat session and all its messages."""
        session = db.query(RagChatSession).filter(RagChatSession.id == session_id).first()
        if session:
            db.delete(session)
            db.commit()
            return True
        return False

    @classmethod
    def get_learned_facts(cls, db: Session, user_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves learned long-term memory facts."""
        facts = db.query(RagMemoryFact).filter(
            RagMemoryFact.is_active == True
        ).order_by(RagMemoryFact.created_at.desc()).limit(limit).all()

        return [
            {
                "id": f.id,
                "subject": f.subject,
                "content": f.content,
                "fact_type": f.fact_type,
                "learned_from": f.learned_from,
                "confidence_score": f.confidence_score,
                "created_at": f.created_at.isoformat() if f.created_at else None
            }
            for f in facts
        ]

    @classmethod
    def delete_learned_fact(cls, db: Session, fact_id: str) -> bool:
        """Deletes or deactivates a learned fact."""
        fact = db.query(RagMemoryFact).filter(RagMemoryFact.id == fact_id).first()
        if fact:
            db.delete(fact)
            db.commit()
            return True
        return False

    @classmethod
    def chat_completion(
        cls,
        db: Session,
        query: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        top_k: int = 4,
        document_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        RAG Chat Completion with Multi-Turn Persistent Memory (Redis + PostgreSQL) & Self-Growth:
        1. Retrieves session conversation history from Redis L1 cache or PostgreSQL L2 database.
        2. Retrieves top-k most relevant Markdown chunks via vector similarity search.
        3. Retrieves dynamic learned facts & user corrections from RagMemoryFact.
        4. Injects context and learned facts into LLM.
        5. Persists messages to both Redis and PostgreSQL.
        """
        start_time = time.perf_counter()
        session_id = session_id or f"sess_{uuid.uuid4().hex[:10]}"

        # 1. Retrieve Active Messages (Redis L1 cache or PostgreSQL L2 fallback)
        active_messages = list(messages) if messages else []
        if not active_messages and session_id:
            redis_history = RedisService.get_chat_history(session_id, limit=8)
            if redis_history:
                active_messages = redis_history
            else:
                db_msgs = cls.get_session_messages(db, session_id)
                if db_msgs:
                    active_messages = [{"role": m["role"], "content": m["content"]} for m in db_msgs[-8:]]

        # 2. Check Semantic RAG Cache (if standalone query without previous turns)
        if not active_messages:
            cached_res = RedisService.get_rag_cache(query, document_id)
            if cached_res:
                cached_res["latency_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                return cached_res

        # 3. Context-aware search query without assistant message pollution
        search_query = query.strip()
        user_history = [
            str(m.get("content")).strip() for m in active_messages 
            if isinstance(m, dict) and m.get("role") == "user" and m.get("content")
        ]
        # Only prepend previous user context if the current query is very short and contains anaphoric pronouns
        if user_history and len(query.split()) < 4:
            q_lower = query.lower()
            if any(p in q_lower for p in ["itu", "tersebut", "nya", "ini", "dia", "maksud", "bagaimana", "tekanannya"]):
                search_query = f"{user_history[-1][:80]} {query.strip()}"

        # 4. Retrieve relevant chunks from documents (with bilingual expansion)
        chunks = cls.search_similar_chunks(db, search_query, top_k=top_k, document_id=document_id)
        if not chunks and search_query != query.strip():
            chunks = cls.search_similar_chunks(db, query.strip(), top_k=top_k, document_id=document_id)

        # 5. Retrieve learned facts from Self-Growth Memory
        learned_facts = cls.search_learned_facts(db, search_query, top_k=3, user_id=user_id)

        # 6. Build Context Prompt
        context_parts = []
        sources = []

        # Add learned facts first with high priority
        if learned_facts:
            facts_text = "\n".join([f"• [{f['fact_type'].upper()}]: {f['content']}" for f in learned_facts])
            context_parts.append(f"[Memori & Aturan Khusus yang Dipelajari dari Pengguna]:\n{facts_text}")

        for idx, c in enumerate(chunks, 1):
            source_tag = f"[Sumber #{idx}: {c['filename']}"
            if c.get('heading'):
                source_tag += f" - {c['heading']}"
            source_tag += "]"

            context_parts.append(f"{source_tag}\n{c['content']}")
            sources.append({
                "source_id": idx,
                "filename": c["filename"],
                "heading": c.get("heading"),
                "s3_url": c.get("s3_url"),
                "similarity_score": c["similarity_score"]
            })

        combined_context = "\n\n---\n\n".join(context_parts) if context_parts else "Tidak ada dokumen yang relevan ditemukan di basis pengetahuan."

        # 7. Formulate System Prompt & Multi-Turn Message History
        system_instruction = custom_system_prompt or (
            "Anda adalah Hero Assistant, asisten AI resmi yang cerdas, efisien, dan profesional.\n\n"
            "ATURAN WAJIB FORMAT JAWABAN (STRICT RULES):\n"
            "1. BAHASA: Wajib 100% menggunakan Bahasa Indonesia yang baku, jelas, ringkas, dan profesional. Jangan pernah menjawab dalam Bahasa Inggris kecuali nama model/merek, istilah teknis, satuan, atau kode part/ukuran yang tidak dapat diterjemahkan.\n"
            "2. HANYA JAWABAN AKHIR (NO META-THOUGHTS / NO CONSTRAINT CHECKS): Langsung berikan jawaban akhir yang siap dibaca oleh pengguna tanpa catatan meta evaluasi aturan/checklist internal.\n"
            "3. WAJIB TABEL MARKDOWN UNTUK DATA SPESIFIKASI/TABULAR:\n"
            "   - Jika jawaban memuat data spesifikasi ban, ukuran, tekanan angin (pressure/bar/psi), beban/muatan (load index/kg/lbs), kecepatan, dimensi, kode part, atau perbandingan tipe ban, ANDA WAJIB MENYAJIKANNYA DALAM TABEL MARKDOWN LENGKAP:\n"
            "     | Model / Tipe | Ukuran Ban | Tekanan Angin (Bar / PSI) | Beban / Load (kg) | Kecepatan (km/h) |\n"
            "     | :--- | :--- | :--- | :--- | :--- |\n"
            "     | ... | ... | ... | ... | ... |\n"
            "   - Untuk penjelasan teks atau langkah operasional lainnya, gunakan poin-poin (bullet points) yang rapi, ringkas, dan to-the-point.\n"
            "4. BERBASIS KONTEKS DOKUMEN & MEMORI: Analisis dan terjemahkan informasi teknis dari Konteks Dokumen Pengetahuan (termasuk istilah bahasa Inggris seperti 'inflation pressure', 'load capacity', 'tread depth', 'operating pressure') ke jawaban Bahasa Indonesia yang akurat dan jelas.\n"
            "5. JIKA TIDAK DITEMUKAN: Sampaikan secara sopan dan singkat (cukup 1 kalimat) bahwa informasi spesifik tersebut tidak ditemukan dalam basis pengetahuan dokumen."
        )

        current_prompt = f"""Konteks Dokumen & Memori Pengetahuan (Markdown):
----------------------------------------
{combined_context}
----------------------------------------

Pertanyaan Pengguna:
{query}"""

        llm_messages = [{"role": "system", "content": system_instruction}]

        # Inject previous conversation turns (up to last 6 messages)
        if active_messages:
            past_msgs = active_messages[:-1] if active_messages and active_messages[-1].get("content") == query else active_messages
            for m in past_msgs[-6:]:
                if isinstance(m, dict) and m.get("role") in ["user", "assistant"] and m.get("content"):
                    llm_messages.append({
                        "role": m["role"],
                        "content": str(m["content"]).strip()
                    })

        llm_messages.append({"role": "user", "content": current_prompt})

        # 8. Invoke LLM
        answer = cls._call_llm_messages(llm_messages)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 9. Persist to Redis (L1) and PostgreSQL Database (L2)
        user_msg = cls.save_message_to_db(
            db=db,
            session_id=session_id,
            role="user",
            content=query,
            user_id=user_id,
            document_id=document_id
        )

        assistant_msg = cls.save_message_to_db(
            db=db,
            session_id=session_id,
            role="assistant",
            content=answer,
            sources=sources,
            retrieved_chunks_count=len(chunks),
            latency_ms=elapsed_ms,
            user_id=user_id,
            document_id=document_id
        )

        RedisService.save_chat_turn(session_id, "user", query)
        RedisService.save_chat_turn(session_id, "assistant", answer, sources=sources)

        result = {
            "query": query,
            "answer": answer,
            "sources": sources,
            "learned_facts": learned_facts,
            "session_id": session_id,
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
            "retrieved_chunks_count": len(chunks),
            "latency_ms": elapsed_ms,
            "from_cache": False
        }

        if not active_messages:
            RedisService.set_rag_cache(query, document_id, result)

        return result

    @staticmethod
    def _clean_llm_response(text: str) -> str:
        """
        Sanitizes LLM output to remove XML reasoning/thought tags, meta-reasoning,
        and constraint check checklists (e.g. 'Check against Constraints', 'Self-Correction').
        """
        if not text:
            return ""

        cleaned = text
        # 1. Remove XML reasoning/thought tags (<think>...</think>, <thought>...</thought>)
        if re.search(r'</(?:think|thought)>', cleaned, flags=re.IGNORECASE):
            parts = re.split(r'</(?:think|thought)>', cleaned, flags=re.IGNORECASE)
            cleaned = parts[-1].strip()
        else:
            cleaned = re.sub(r'<(?:think|thought)>[\s\S]*$', '', cleaned, flags=re.IGNORECASE).strip()

        # 2. Remove meta-reasoning and constraint check blocks
        constraint_patterns = [
            r'(?i)\n*(?:(?:\d+[\.\)]\s*)?(?:Check\s+(?:against\s+)?Constraints?|Constraint\s+Check|Self-[Cc]orrection(?:/Refinement)?|Refinement\s+during\s+thought|Thinking\s+Process|Thought\s+Process|Proses\s+Berpikir|Evaluasi\s+Batasan)[\s\S]*)$',
            r'(?i)^\s*-\s*(?:Language|Efficient\s*&\s*direct|Bullet\s*points/table|Based\s*on\s*context|Citation|Matches\s*all\s*constraints|Self-Correction).*$\n?',
            r'(?i)^Here\'s a thinking process:[\s\S]*?\n(?=[A-Z0-9#|•\-])',
        ]
        for pattern in constraint_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE)

        # 3. Clean up excessive whitespace/newlines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        
        if not cleaned:
            return "Informasi spesifik mengenai pertanyaan tersebut tidak ditemukan dalam basis pengetahuan dokumen."

        return cleaned

    @staticmethod
    def _call_llm(system_prompt: str, user_prompt: str) -> str:
        """Legacy helper delegating to _call_llm_messages."""
        return RagService._call_llm_messages([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])

    @staticmethod
    def _call_llm_messages(messages: List[Dict[str, str]]) -> str:
        """
        Invokes LLM with full conversation messages list.
        Priority:
        1. Groq (Ultra-fast LPU, default model: qwen/qwen3.6-27b)
        2. OpenRouter
        3. Google Gemini API
        """
        import requests

        groq_key = os.getenv("GROQ_API_KEY", "")
        groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")

        # 1. Groq (Ultra-Fast LPU Engine)
        if groq_key:
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": groq_model,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 2048,
                        "reasoning_format": "hidden"
                    },
                    timeout=25
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return RagService._clean_llm_response(content)
                else:
                    logger.warning(f"[RagService] Groq API returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"[RagService] Groq API call error: {e}")

        # 2. OpenRouter Fallback
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        openrouter_model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
        if openrouter_key:
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://rarayvision.dfs.co.id",
                        "X-Title": "Hero Assistant RAG"
                    },
                    json={
                        "model": openrouter_model,
                        "messages": messages,
                        "temperature": 0.3
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return RagService._clean_llm_response(content)
                else:
                    logger.warning(f"[RagService] OpenRouter returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"[RagService] OpenRouter LLM call error: {e}")

        # 3. Google Gemini Fallback
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                # Combine messages into prompt for Gemini
                gemini_text = "\n\n".join([f"[{m['role'].upper()}]: {m['content']}" for m in messages])
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=gemini_text
                )
                if response and response.text:
                    return RagService._clean_llm_response(response.text)
            except Exception as e:
                logger.error(f"[RagService] Gemini LLM call error: {e}")

        return (
            "⚠️ **Catatan Sistem:** API Key LLM (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, atau `GEMINI_API_KEY`) belum dikonfigurasi di file `.env`.\n\n"
            "Namun, potongan dokumen yang relevan dari pgvector berhasil ditemukan dan tercantum pada panel sumber di bawah."
        )
