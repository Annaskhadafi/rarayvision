import os
import re
import uuid
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.database.rag_models import RagDocument, RagDocumentChunk
from backend.app.services.anydoc_service import AnyDocService

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


class RagService:
    @staticmethod
    def get_embedding_info() -> Dict[str, Any]:
        """Returns active embedding provider and LLM engine info."""
        groq_key = os.getenv("GROQ_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

        active_llm = "Groq LPU (qwen/qwen3.6-27b)" if groq_key else "OpenRouter"

        return {
            "default_provider": "local_fastembed",
            "local_embedding_model": "BAAI/bge-small-en-v1.5 (384 dimensions, ONNX offline, 100% Free)",
            "active_llm": active_llm,
            "groq_configured": bool(groq_key),
            "groq_model": os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b"),
            "gemini_configured": bool(gemini_key),
            "openrouter_configured": bool(openrouter_key),
            "vector_dimensions": 384
        }

    @classmethod
    def generate_embeddings(cls, texts: List[str]) -> List[List[float]]:
        """
        Generates vector embeddings for a list of text strings.
        Defaults to high-speed local FastEmbed ONNX (100% free, 384-d).
        """
        if not texts:
            return []

        model = get_fastembed_model()
        if model:
            try:
                # FastEmbed yields numpy arrays
                embeddings_gen = model.embed(texts)
                return [list(map(float, emb)) for emb in embeddings_gen]
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
        Semantically splits Markdown text into chunks while preserving headings,
        tables, and paragraph boundaries.
        """
        if not markdown_text or not markdown_text.strip():
            return []

        # Split by paragraphs or markdown headers
        raw_sections = re.split(r'\n(?=#{1,3}\s)', markdown_text)
        chunks = []
        current_heading = "General"

        for sec in raw_sections:
            sec_str = sec.strip()
            if not sec_str:
                continue

            # Check if section starts with a heading
            header_match = re.match(r'^(#{1,3})\s+(.*)$', sec_str.splitlines()[0])
            if header_match:
                current_heading = header_match.group(2).strip()

            # If section is within max_chunk_chars, keep as one chunk
            if len(sec_str) <= max_chunk_chars:
                chunks.append({
                    "content": sec_str,
                    "heading": current_heading,
                    "char_count": len(sec_str),
                    "token_estimate": len(sec_str.split())
                })
            else:
                # Split large section by paragraphs or lines
                paragraphs = sec_str.split("\n\n")
                buf = []
                buf_len = 0

                for p in paragraphs:
                    p_clean = p.strip()
                    if not p_clean:
                        continue

                    if buf_len + len(p_clean) > max_chunk_chars and buf:
                        chunk_text = "\n\n".join(buf)
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
        3. Splits Markdown into semantic chunk blocks.
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
        Executes semantic vector similarity search using cosine similarity across embeddings.
        """
        query_vec = cls.generate_single_embedding(query)
        return cls._in_memory_similarity_search(db, query_vec, top_k, document_id)

    @classmethod
    def _in_memory_similarity_search(
        cls,
        db: Session,
        query_vec: List[float],
        top_k: int,
        document_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fallback Python cosine similarity search."""
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

        scored = []
        for chunk, fname, s3_link, fmt in rows:
            if chunk.embedding is not None:
                c_arr = np.array(chunk.embedding, dtype=float)
                norm_c = np.linalg.norm(c_arr)
                if norm_c > 0:
                    sim = float(np.dot(q_arr, c_arr) / (norm_q * norm_c))
                else:
                    sim = 0.0
            else:
                sim = 0.0

            scored.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "filename": fname,
                "format": fmt,
                "s3_url": s3_link,
                "chunk_index": chunk.chunk_index,
                "heading": chunk.heading,
                "content": chunk.content,
                "similarity_score": round(sim, 4),
                "distance": round(1.0 - sim, 4)
            })

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored[:top_k]

    @classmethod
    def chat_completion(
        cls,
        db: Session,
        query: str,
        top_k: int = 4,
        document_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RAG Chat Pipeline:
        1. Retrieves top-k most relevant Markdown chunks via vector similarity search.
        2. Constructs knowledge context.
        3. Calls LLM (OpenRouter / Nemotron / OpenAI / Gemini).
        4. Returns structured answer with source citations.
        """
        start_time = time.perf_counter()

        # 1. Retrieve relevant chunks
        chunks = cls.search_similar_chunks(db, query, top_k=top_k, document_id=document_id)

        # 2. Build Context Prompt
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

        # 3. Formulate Prompt
        system_instruction = custom_system_prompt or (
            "Anda adalah AI Assistant RAG cerdas untuk Raray Vision. "
            "Tugas Anda adalah menjawab pertanyaan pengguna secara akurat, jelas, dan profesional "
            "berdasarkan KONTEKS DOKUMEN MARKDOWN yang disediakan di bawah ini.\n"
            "Jika informasi tidak terdapat pada konteks, sampaikan dengan sopan bahwa informasi tidak ditemukan dalam basis pengetahuan.\n"
            "Sebutkan rujukan sumber dokumen jika relevan."
        )

        llm_prompt = f"""Konteks Dokumen Pengetahuan (Markdown):
----------------------------------------
{combined_context}
----------------------------------------

Pertanyaan Pengguna:
{query}

Jawaban:"""

        # 4. Invoke LLM
        answer = cls._call_llm(system_instruction, llm_prompt)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "retrieved_chunks_count": len(chunks),
            "latency_ms": elapsed_ms
        }

    @staticmethod
    def _call_llm(system_prompt: str, user_prompt: str) -> str:
        """
        Invokes LLM for grounded RAG answer generation.
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
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
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
                        "X-Title": "Raray Vision RAG"
                    },
                    json={
                        "model": openrouter_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
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
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=f"{system_prompt}\n\n{user_prompt}"
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.error(f"[RagService] Gemini LLM call error: {e}")

        return (
            "⚠️ **Catatan Sistem:** API Key LLM (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, atau `GEMINI_API_KEY`) belum dikonfigurasi di file `.env`.\n\n"
            "Namun, potongan dokumen yang relevan dari pgvector berhasil ditemukan dan tercantum pada panel sumber di bawah."
        )
