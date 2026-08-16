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
    from app.database.rag_models import RagDocument, RagDocumentChunk
    from app.services.anydoc_service import AnyDocService
    from app.services.redis_service import RedisService
except ImportError:
    from backend.app.database.rag_models import RagDocument, RagDocumentChunk
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
        Executes high-accuracy Hybrid Search (Dense Vector Cosine Similarity + BM25 Sparse Lexical Scoring with RRF).
        """
        query_vec = cls.generate_single_embedding(query)
        return cls._hybrid_similarity_search(db, query, query_vec, top_k, document_id)

    @classmethod
    def _hybrid_similarity_search(
        cls,
        db: Session,
        query: str,
        query_vec: List[float],
        top_k: int,
        document_id: Optional[str] = None
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
        scored = []
        for idx, item in enumerate(items):
            r_vec = vec_rank_map[idx]
            r_bm25 = bm25_rank_map[idx]
            rrf_score = (1.0 / (60.0 + r_vec)) + (1.0 / (60.0 + r_bm25))

            # Exact phrase match boost
            content_lower = item["content"].lower()
            heading_lower = item["heading"].lower()
            if q_lower in heading_lower:
                rrf_score += 0.015
            elif q_lower in content_lower:
                rrf_score += 0.008

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
    def chat_completion(
        cls,
        db: Session,
        query: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        top_k: int = 4,
        document_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RAG Chat Completion with Multi-Turn Conversation Memory & Redis Caching:
        1. Checks Redis cache for instant response if query is standalone.
        2. Retrieves session conversation history from Redis if session_id is provided.
        3. Analyzes conversation history to construct contextual search query.
        4. Retrieves top-k most relevant Markdown chunks via vector similarity search.
        5. Constructs knowledge context.
        6. Passes full conversation thread + grounded context to LLM (Groq / OpenRouter / Gemini).
        7. Saves turns to Redis session memory and caches response.
        """
        start_time = time.perf_counter()

        # 1. Check Redis Session Memory
        active_messages = list(messages) if messages else []
        if not active_messages and session_id:
            redis_history = RedisService.get_chat_history(session_id, limit=8)
            if redis_history:
                active_messages = redis_history

        # 2. Check Semantic RAG Cache (if standalone query without previous turns)
        if not active_messages:
            cached_res = RedisService.get_rag_cache(query, document_id)
            if cached_res:
                cached_res["latency_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                return cached_res

        # 3. Context-aware search query
        search_query = query.strip()
        history_for_search = []
        if active_messages:
            for m in active_messages:
                if isinstance(m, dict) and m.get("content") and m.get("role") in ["user", "assistant"]:
                    c_text = re.sub(r'📎 Sumber Rujukan[\s\S]*$', '', str(m["content"])).strip()
                    if c_text:
                        history_for_search.append(c_text)

        if len(history_for_search) >= 2 and len(query.split()) < 7:
            # Short follow-up question -> combine with previous topic for better vector retrieval
            search_query = f"{history_for_search[-2][:80]} {query.strip()}"

        # 4. Retrieve relevant chunks
        chunks = cls.search_similar_chunks(db, search_query, top_k=top_k, document_id=document_id)
        if not chunks and search_query != query.strip():
            chunks = cls.search_similar_chunks(db, query.strip(), top_k=top_k, document_id=document_id)

        # 5. Build Context Prompt
        context_parts = []
        sources = []

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

        # 6. Formulate Prompt & Multi-Turn Message History
        system_instruction = custom_system_prompt or (
            "Anda adalah Hero Assistant, asisten AI cerdas, efisien, dan profesional.\n\n"
            "PANDUAN BERPIKIR & FORMAT JAWABAN (WAJIB DIPATUHI):\n"
            "1. KONSISTENSI BAHASA: Gunakan Bahasa Indonesia baku dan profesional secara konsisten (baik dalam proses berpikir/penalaran maupun jawaban akhir).\n"
            "2. EFISIEN & LANGSUNG KE INTI: Berikan jawaban yang padat, efisien, to-the-point, dan hindari kata-kata atau kalimat yang berulang-ulang tanpa basa-basi panjang.\n"
            "3. STRUKTUR POIN-POIN & TABEL MARKDOWN:\n"
            "   - Jika data/informasi memuat perbandingan, daftar ukuran/spesifikasi ban, kode part/SKU, daftar harga, stok inventaris, rincian data tabular, jadwal, atau informasi multi-kolom, WAJIB sajikan dalam bentuk TABEL MARKDOWN yang rapi (`| Header 1 | Header 2 | ... |` dan `| :--- | :--- | ... |`).\n"
            "   - Untuk penjelasan non-tabular, susun dalam bentuk poin-poin (bullet points) yang rapi, ringkas, dan jelas.\n"
            "4. BERBASIS KONTEKS DOKUMEN: Jawab secara akurat berdasarkan KONTEKS DOKUMEN MARKDOWN yang disediakan serta riwayat percakapan sebelumnya.\n"
            "5. RUJUKAN SUMBER: Cantumkan rujukan nama dokumen atau bagian relevan jika tersedia.\n"
            "6. JIKA TIDAK DITEMUKAN: Sampaikan secara singkat dan sopan (cukup 1 kalimat) bahwa informasi tidak ditemukan dalam basis pengetahuan."
        )

        current_prompt = f"""Konteks Dokumen Pengetahuan (Markdown):
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

        # 7. Invoke LLM
        answer = cls._call_llm_messages(llm_messages)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        result = {
            "query": query,
            "answer": answer,
            "sources": sources,
            "session_id": session_id,
            "retrieved_chunks_count": len(chunks),
            "latency_ms": elapsed_ms,
            "from_cache": False
        }

        # 8. Persist to Redis Memory & Cache
        if session_id:
            RedisService.save_chat_turn(session_id, "user", query)
            RedisService.save_chat_turn(session_id, "assistant", answer, sources=sources)

        if not active_messages:
            RedisService.set_rag_cache(query, document_id, result)

        return result

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
                        "max_tokens": 2048
                    },
                    timeout=25
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    clean_content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                    return clean_content or content.strip()
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
                    return data["choices"][0]["message"]["content"].strip()
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
                    return response.text.strip()
            except Exception as e:
                logger.error(f"[RagService] Gemini LLM call error: {e}")

        return (
            "⚠️ **Catatan Sistem:** API Key LLM (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, atau `GEMINI_API_KEY`) belum dikonfigurasi di file `.env`.\n\n"
            "Namun, potongan dokumen yang relevan dari pgvector berhasil ditemukan dan tercantum pada panel sumber di bawah."
        )
