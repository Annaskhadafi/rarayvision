import os
import re
import uuid
import time
import logging
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

try:
    from ..database.rag_models import (
        RagDocument, RagDocumentChunk,
        RagChatSession, RagChatMessage, RagMemoryFact
    )
    from .anydoc_service import AnyDocService
    from .redis_service import RedisService
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
_fastembed_reranker_instance = None

# Global HTTP Session with Keep-Alive & Connection Pooling
_http_session = None

# Global In-Memory Vector & Chunk Cache (Eliminates repeated multi-second DB scans)
_chunk_cache = None
_chunk_cache_lock = threading.Lock()

_memory_facts_cache = None
_memory_facts_cache_lock = threading.Lock()


def get_http_session():
    global _http_session
    if _http_session is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        _http_session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=40,
            max_retries=Retry(total=1, backoff_factor=0.1, status_forcelist=[502, 503, 504])
        )
        _http_session.mount("https://", adapter)
        _http_session.mount("http://", adapter)
    return _http_session


def get_fastembed_model():
    global _fastembed_instance
    if _fastembed_instance is None:
        try:
            from fastembed import TextEmbedding
            # BAAI/bge-small-en-v1.5 is fast (384-d), free, lightweight (~130MB), high MTEB score
            threads = min(4, os.cpu_count() or 2)
            _fastembed_instance = TextEmbedding("BAAI/bge-small-en-v1.5", threads=threads)
            logger.info(f"[RagService] FastEmbed ONNX initialized (384-d, {threads} threads).")
        except Exception as e:
            logger.error(f"[RagService] Failed to load FastEmbed: {e}")
            _fastembed_instance = False
    return _fastembed_instance


def get_reranker_model():
    global _fastembed_reranker_instance
    if _fastembed_reranker_instance is None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            # Xenova/ms-marco-MiniLM-L-6-v2 is ultra-fast (~80MB ONNX), free & accurate
            model_name = os.getenv("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
            threads = min(4, os.cpu_count() or 2)
            _fastembed_reranker_instance = TextCrossEncoder(model_name, threads=threads)
            logger.info(f"[RagService] FastEmbed Cross-Encoder Reranker initialized ({model_name}, {threads} threads).")
        except Exception as e:
            logger.error(f"[RagService] Failed to load FastEmbed Reranker: {e}")
            _fastembed_reranker_instance = False
    return _fastembed_reranker_instance


# Domain Bilingual Query Expansion Dictionary (Indonesian <-> Technical Engineering / Tire Standards)
DOMAIN_SYNONYMS = {
    # Pressure & Inflation
    "tekanan": ["pressure", "inflation", "operating pressure", "bar", "psi", "kpa", "cold pressure", "inflation pressure", "nominal pressure"],
    "angin": ["pressure", "inflation", "psi", "bar", "kpa", "cold pressure"],
    "pressure": ["tekanan", "angin", "inflation", "bar", "psi", "kpa", "cold pressure"],
    "inflation": ["tekanan", "angin", "pressure", "bar", "psi", "cold inflation"],
    "bar": ["tekanan", "psi", "kpa", "pressure", "cold pressure"],
    "psi": ["tekanan", "bar", "kpa", "pressure", "cold pressure"],
    
    # Tires & Types
    "ban": ["tire", "tyre", "earthmover", "otr", "tubeless", "radial", "bias"],
    "tire": ["ban", "tyre", "earthmover", "otr", "tubeless"],
    "tyre": ["ban", "tire", "earthmover", "otr", "tubeless"],
    "otr": ["off-the-road", "earthmover", "ban tambang", "haul truck", "loader", "grader"],
    "radial": ["ban radial", "tubeless", "steel belted"],
    
    # Load & Capacity
    "muatan": ["load", "payload", "capacity", "kg", "lbs", "load index", "maximum load"],
    "beban": ["load", "payload", "capacity", "kg", "lbs", "load index", "maximum load"],
    "kapasitas": ["capacity", "payload", "load", "volume", "ton"],
    "load": ["beban", "muatan", "payload", "capacity", "kg", "lbs", "load index"],
    "payload": ["muatan", "beban", "load", "tonase", "kapasitas"],
    
    # Speed & Distance
    "kecepatan": ["speed", "km/h", "mph", "speed symbol", "speed limit", "maximum speed"],
    "speed": ["kecepatan", "km/h", "mph", "speed symbol"],
    
    # Dimensions & Rim
    "ukuran": ["size", "dimension", "radial", "rim", "diameter", "width"],
    "dimensi": ["dimension", "size", "width", "diameter", "overall diameter", "section width"],
    "velg": ["rim", "wheel", "flange", "rim width"],
    "pelek": ["rim", "wheel", "flange", "rim width"],
    "rim": ["velg", "pelek", "wheel", "flange", "rim width"],
    "lebar": ["width", "section width", "overall width"],
    "diameter": ["overall diameter", "outer diameter", "rim diameter"],
    
    # Tread & Groove
    "tapak": ["tread", "tread depth", "otd", "pattern", "groove", "non-skid"],
    "alur": ["tread", "tread depth", "otd", "groove", "pattern"],
    "kembangan": ["tread", "pattern", "otd", "tread depth"],
    "kedalaman": ["depth", "tread depth", "otd", "mm", "32nds", "remaining tread"],
    "tread": ["tapak", "alur", "kembangan", "tread depth", "otd"],
    "otd": ["original tread depth", "tread depth", "kedalaman tapak", "mm"],
    
    # Temperature & Heat
    "panas": ["tkph", "tmph", "temperature", "heat", "heat generation"],
    "suhu": ["temperature", "tkph", "tmph", "heat", "celsius"],
    "tkph": ["tonne kilometer per hour", "tmph", "ton mile per hour", "heat rate", "suhu ban"],
    
    # Weight & Mass
    "berat": ["weight", "kg", "lbs", "mass", "tire weight"],
    "weight": ["berat", "massa", "kg", "lbs"],
    
    # Type, Code & Star Rating
    "tipe": ["type", "pattern", "star rating", "ply rating", "code", "tra code"],
    "bintang": ["star", "star rating", "ply rating", "pr", "load index"],
    "rating": ["star rating", "ply rating", "pr", "load index", "speed symbol"],
    "tra": ["tra code", "e-3", "e-4", "l-3", "l-4", "l-5", "g-2", "c-1"],
    
    # Operations, Mounting & Safety
    "aturan": ["sop", "procedure", "rule", "instruction", "standard", "safety"],
    "prosedur": ["sop", "procedure", "step", "instruction", "safety guideline"],
    "dongkrak": ["hydraulic jack", "jack", "lifting", "stand"],
    "bongkar": ["demounting", "removal", "disassembly", "deflation"],
    "pasang": ["mounting", "assembly", "installation", "inflation"],
    "baut": ["torque", "nut", "stud", "tightening", "ft-lbs", "nm"],
    "torsi": ["torque", "tightening torque", "nm", "ft-lbs", "wrench"]
}


def expand_bilingual_query(query: str) -> str:
    """
    Expands bilingual query terms (Indonesian <-> English) with domain engineering technical synonyms.
    Also extracts and prioritizes exact tire sizes (e.g. 27.00R49, 33.00R51, 14.00-24) and pressure terms.
    """
    if not query:
        return ""
    q_clean = query.lower().strip()
    words = re.findall(r'[a-zA-Z0-9_\-\.\/]+', q_clean)
    added_terms = []
    
    # 1. Expand technical synonyms
    for w in words:
        if w in DOMAIN_SYNONYMS:
            added_terms.extend(DOMAIN_SYNONYMS[w])
            
    # 2. Extract technical patterns like tire size (e.g. 27.00R49, 33.00R51, 29.5R25, 14.00-24)
    tire_sizes = re.findall(r'\b\d{1,2}(?:\.\d{1,2})?(?:[rR\-xX\/])\d{1,2}(?:\.\d{1,2})?\b', query)
    if tire_sizes:
        for sz in tire_sizes:
            added_terms.append(sz.upper())
            added_terms.append(sz.lower())

    if added_terms:
        # Keep unique terms in order
        unique_added = list(dict.fromkeys(added_terms))
        return f"{query} {' '.join(unique_added[:12])}"
    return query


def tokenize_text(text: str) -> List[str]:
    """Tokenize alphanumeric words, technical identifiers, SKU numbers, and size codes."""
    if not text:
        return []
    clean = text.lower()
    tokens = re.findall(r'[a-zA-Z0-9_\-\.\/]+', clean)
    return [t.strip('.-_/') for t in tokens if len(t.strip('.-_/')) >= 1]


def compute_bm25_scores(query: str, items: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """
    High-speed vectorized Okapi BM25 scores calculation for exact keyword and numerical code matching.
    """
    import numpy as np
    query_tokens = tokenize_text(query)
    if not query_tokens or not items:
        return [0.0] * len(items)

    N = len(items)
    df = {q_tok: 0 for q_tok in query_tokens}
    doc_token_counts = []
    doc_lens = []

    for it in items:
        text_lower = f"{it.get('heading', '')} {it.get('content', '')}".lower()
        words_approx = len(text_lower) // 5 + 1
        doc_lens.append(words_approx)

        tf_dict = {}
        for q_tok in query_tokens:
            if q_tok in text_lower:
                cnt = text_lower.count(q_tok)
                if cnt > 0:
                    tf_dict[q_tok] = cnt
                    df[q_tok] += 1
        doc_token_counts.append(tf_dict)

    avgdl = sum(doc_lens) / max(len(doc_lens), 1) if doc_lens else 1.0
    if avgdl == 0:
        avgdl = 1.0

    idf_dict = {
        q_tok: max(0.1, float(np.log((N - df[q_tok] + 0.5) / (df[q_tok] + 0.5) + 1.0)))
        for q_tok in query_tokens
    }

    scores = []
    for idx, tf_dict in enumerate(doc_token_counts):
        if not tf_dict:
            scores.append(0.0)
            continue
        doc_len = doc_lens[idx]
        denom = k1 * (1.0 - b + b * (doc_len / avgdl))
        score = 0.0
        for q_tok, tf in tf_dict.items():
            score += idf_dict[q_tok] * ((tf * (k1 + 1.0)) / (tf + denom))
        scores.append(float(score))

    return scores


class RagService:
    @staticmethod
    def get_embedding_info() -> Dict[str, Any]:
        """Returns active embedding provider, reranker info, LLM engine info, and Redis status."""
        groq_key = os.getenv("GROQ_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        active_llm = f"Groq LPU ({groq_model})" if groq_key else ("OpenRouter" if openrouter_key else "Google Gemini")
        reranker_model = os.getenv("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
        reranker_active = bool(get_reranker_model())

        return {
            "default_provider": "local_fastembed",
            "model_name": "BAAI/bge-small-en-v1.5",
            "vector_dimension": 384,
            "pricing": "100% Free & Offline",
            "reranker_model": reranker_model,
            "reranker_enabled": reranker_active,
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
                batch_size = 64
                for i in range(0, len(texts), batch_size):
                    batch_slice = texts[i:i + batch_size]
                    gen = model.embed(batch_slice, batch_size=64)
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
        """Generates embedding vector for a single query string with minimal latency."""
        if not text:
            return [0.0] * 384
        model = get_fastembed_model()
        if model:
            try:
                emb_gen = model.embed([text], batch_size=1)
                return [float(x) for x in next(emb_gen)]
            except Exception as e:
                logger.error(f"[RagService] generate_single_embedding error: {e}")
        return [0.0] * 384

    @staticmethod
    def split_markdown_into_chunks(
        markdown_text: str,
        max_chunk_chars: int = 800,
        overlap_chars: int = 120
    ) -> List[Dict[str, Any]]:
        """
        Semantically splits Markdown text into chunks while preserving heading hierarchy,
        table structure (guaranteeing table headers and column labels on every table chunk),
        and paragraph boundaries.
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
            first_line = sec_str.splitlines()[0] if sec_str.splitlines() else ""
            header_match = re.match(r'^(#{1,4})\s+(.*)$', first_line)
            if header_match:
                level = len(header_match.group(1))
                h_title = header_match.group(2).strip()
                hierarchy_stack[level] = h_title
                hierarchy_stack = {k: v for k, v in hierarchy_stack.items() if k <= level}

            active_headings = [hierarchy_stack[k] for k in sorted(hierarchy_stack.keys())]
            current_heading = " > ".join(active_headings) if active_headings else "General"

            lines = sec_str.splitlines()

            # Check if section contains a markdown table
            has_table = False
            table_header_prefix = ""
            header_end_idx = 0

            for idx in range(min(len(lines) - 1, 5)):
                if "|" in lines[idx] and idx + 1 < len(lines) and ("---" in lines[idx + 1] or ":---" in lines[idx + 1]):
                    has_table = True
                    table_header_prefix = f"{lines[idx]}\n{lines[idx + 1]}\n"
                    header_end_idx = idx + 2
                    break

            # If section is within max_chunk_chars, keep as one chunk
            if len(sec_str) <= max_chunk_chars:
                chunks.append({
                    "content": sec_str,
                    "heading": current_heading,
                    "char_count": len(sec_str),
                    "token_estimate": len(sec_str.split())
                })
            elif has_table and header_end_idx > 0:
                # Specialized table chunking: keep header on every row chunk
                table_rows = [l for l in lines[header_end_idx:] if "|" in l and l.strip()]
                non_table_before = "\n".join(lines[:header_end_idx - 2]).strip()
                if non_table_before:
                    chunks.append({
                        "content": non_table_before,
                        "heading": current_heading,
                        "char_count": len(non_table_before),
                        "token_estimate": len(non_table_before.split())
                    })

                row_buf = []
                cur_len = len(table_header_prefix)
                effective_max = max(max_chunk_chars, 400)

                for row in table_rows:
                    row_len = len(row) + 1
                    if cur_len + row_len > effective_max and row_buf:
                        chunk_body = table_header_prefix + "\n".join(row_buf)
                        chunks.append({
                            "content": chunk_body,
                            "heading": current_heading,
                            "char_count": len(chunk_body),
                            "token_estimate": len(chunk_body.split())
                        })
                        # 1 row overlap for table continuity
                        row_buf = [row_buf[-1]] if len(row_buf) > 1 else []
                        cur_len = len(table_header_prefix) + sum(len(r) + 1 for r in row_buf)

                    row_buf.append(row)
                    cur_len += row_len

                if row_buf:
                    chunk_body = table_header_prefix + "\n".join(row_buf)
                    chunks.append({
                        "content": chunk_body,
                        "heading": current_heading,
                        "char_count": len(chunk_body),
                        "token_estimate": len(chunk_body.split())
                    })
            else:
                # Split large textual section by paragraphs
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

        cls._invalidate_chunk_cache()

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
    def _invalidate_chunk_cache(cls):
        """Invalidates in-memory chunk cache when documents change."""
        global _chunk_cache
        with _chunk_cache_lock:
            _chunk_cache = None
        logger.info("[RagService] In-memory chunk cache invalidated.")

    @classmethod
    def _invalidate_memory_facts_cache(cls):
        """Invalidates in-memory memory facts cache when rules/corrections change."""
        global _memory_facts_cache
        with _memory_facts_cache_lock:
            _memory_facts_cache = None
        logger.info("[RagService] In-memory memory facts cache invalidated.")

    @classmethod
    def _get_cached_chunks(cls, db: Session) -> Dict[str, Any]:
        """Loads and caches all document chunks in RAM for sub-millisecond similarity search."""
        global _chunk_cache
        if _chunk_cache is not None:
            return _chunk_cache

        with _chunk_cache_lock:
            if _chunk_cache is not None:
                return _chunk_cache

            import numpy as np
            q = db.query(
                RagDocumentChunk.id, RagDocumentChunk.document_id, RagDocumentChunk.chunk_index,
                RagDocumentChunk.heading, RagDocumentChunk.content, RagDocumentChunk.embedding,
                RagDocument.filename, RagDocument.s3_url, RagDocument.format
            ).join(RagDocument, RagDocumentChunk.document_id == RagDocument.id)
            rows = q.all()

            items = []
            emb_list = []
            for r in rows:
                items.append({
                    "chunk_id": r.id,
                    "document_id": r.document_id,
                    "filename": r.filename,
                    "format": r.format,
                    "s3_url": r.s3_url,
                    "chunk_index": r.chunk_index,
                    "heading": r.heading or "",
                    "content": r.content or "",
                    "source_type": "document",
                    "fact_type": None,
                    "is_memory": False
                })
                emb = r.embedding
                emb_list.append(emb if emb and len(emb) == 384 else [0.0] * 384)

            if items:
                emb_matrix = np.array(emb_list, dtype=np.float32)
                row_norms = np.linalg.norm(emb_matrix, axis=1)
                row_norms[row_norms == 0] = 1e-9
            else:
                emb_matrix = np.empty((0, 384), dtype=np.float32)
                row_norms = np.empty((0,), dtype=np.float32)

            _chunk_cache = {
                "items": items,
                "matrix": emb_matrix,
                "norms": row_norms
            }
            logger.info(f"[RagService] In-memory chunk cache built: {len(items)} chunks.")
            return _chunk_cache

    @classmethod
    def _get_cached_memory_facts(cls, db: Session) -> Dict[str, Any]:
        """Loads and caches active memory facts in RAM for instant lookup."""
        global _memory_facts_cache
        if _memory_facts_cache is not None:
            return _memory_facts_cache

        with _memory_facts_cache_lock:
            if _memory_facts_cache is not None:
                return _memory_facts_cache

            import numpy as np
            facts = db.query(RagMemoryFact).filter(
                RagMemoryFact.is_active == True,
                RagMemoryFact.learned_from.in_(["user_feedback", "direct_input"])
            ).order_by(RagMemoryFact.created_at.desc()).limit(150).all()

            fact_items = []
            emb_list = []
            raw_facts = []
            for f in facts:
                type_label = "Koreksi" if f.fact_type == "user_correction" else ("Aturan / SOP" if f.fact_type == "rule" else "Memori Pengetahuan")
                fact_items.append({
                    "chunk_id": f.id,
                    "document_id": "memory",
                    "filename": f"🧠 {type_label}",
                    "format": "memory",
                    "s3_url": None,
                    "chunk_index": 0,
                    "heading": f.subject or type_label,
                    "content": f.content or "",
                    "source_type": "memory",
                    "fact_type": f.fact_type,
                    "is_memory": True
                })
                raw_facts.append(f)
                emb = f.embedding
                emb_list.append(emb if emb and len(emb) == 384 else [0.0] * 384)

            if fact_items:
                emb_matrix = np.array(emb_list, dtype=np.float32)
                row_norms = np.linalg.norm(emb_matrix, axis=1)
                row_norms[row_norms == 0] = 1e-9
            else:
                emb_matrix = np.empty((0, 384), dtype=np.float32)
                row_norms = np.empty((0,), dtype=np.float32)

            _memory_facts_cache = {
                "items": fact_items,
                "matrix": emb_matrix,
                "norms": row_norms,
                "raw_facts": raw_facts
            }
            return _memory_facts_cache

    @classmethod
    def rerank_chunks(
        cls,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Applies ONNX Cross-Encoder Reranking to candidate chunks for maximum retrieval precision.
        Computes deep semantic interaction scores between query and document text.
        Transforms raw logits into normalized confidence scores [0.0 - 1.0] using Sigmoid.
        """
        if not chunks or not query:
            return chunks[:top_k]

        reranker = get_reranker_model()
        if not reranker:
            return chunks[:top_k]

        try:
            import numpy as np

            # Combine heading and content for full structural context
            candidate_texts = []
            for c in chunks:
                heading = c.get("heading", "").strip()
                content = c.get("content", "").strip()
                if heading and heading != "General":
                    candidate_texts.append(f"[{heading}]\n{content}")
                else:
                    candidate_texts.append(content)

            raw_scores = list(reranker.rerank(query, candidate_texts))

            reranked = []
            for idx, c in enumerate(chunks):
                raw_score = float(raw_scores[idx]) if idx < len(raw_scores) else 0.0
                # Numerically stable sigmoid: 1 / (1 + exp(-x))
                if raw_score >= 0:
                    norm_score = float(1.0 / (1.0 + np.exp(-raw_score)))
                else:
                    z = float(np.exp(raw_score))
                    norm_score = float(z / (1.0 + z))

                # Boost user memory/correction items slightly
                if c.get("is_memory"):
                    norm_score = min(1.0, norm_score + 0.08)

                chunk_copy = dict(c)
                chunk_copy["vector_score"] = c.get("similarity_score", 0.0)
                chunk_copy["raw_reranker_logit"] = round(raw_score, 4)
                chunk_copy["reranker_score"] = round(norm_score, 4)
                # Primary similarity score becomes the calibrated reranker score
                chunk_copy["similarity_score"] = round(norm_score, 4)
                reranked.append(chunk_copy)

            # Sort strictly descending by reranker score
            reranked.sort(key=lambda x: x["reranker_score"], reverse=True)
            return reranked[:top_k]
        except Exception as e:
            logger.warning(f"[RagService] Reranker execution failed, fallback to vector ranking: {e}")
            return chunks[:top_k]

    @classmethod
    def search_similar_chunks(
        cls,
        db: Session,
        query: str,
        top_k: int = 4,
        document_id: Optional[str] = None,
        enable_rerank: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Two-stage Hybrid retrieval pipeline:
        1. Recall Stage: Hybrid Search (Vector Cosine Similarity + BM25 Lexical Matching with RRF Fusion).
           Automatically expands bilingual technical terms to ensure cross-lingual and exact spec recall.
        2. Precision Stage: ONNX Cross-Encoder Reranks candidates against the specific user query.
        """
        if not query or not query.strip():
            return []

        expanded_query = expand_bilingual_query(query)
        query_vec = cls.generate_single_embedding(expanded_query)

        # Retrieve wider candidate pool for cross-encoder reranking
        candidate_k = max(top_k * 3, 15) if enable_rerank else top_k
        candidates = cls._similarity_search(
            db=db,
            query=query,
            query_vec=query_vec,
            top_k=candidate_k,
            document_id=document_id,
            expanded_query=expanded_query
        )

        if not candidates or not enable_rerank:
            return candidates[:top_k]

        return cls.rerank_chunks(query, candidates, top_k=top_k)

    @classmethod
    def _similarity_search(
        cls,
        db: Session,
        query: str,
        query_vec: List[float],
        top_k: int,
        document_id: Optional[str] = None,
        expanded_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        In-Memory Hybrid Search:
        Combines Vector Cosine Similarity (semantic understanding) and Okapi BM25 (exact keyword & number matching)
        using Reciprocal Rank Fusion (RRF). Eliminates hard threshold drop-offs to prevent false negative retrieval.
        """
        import numpy as np

        cached_doc_data = cls._get_cached_chunks(db)
        cached_mem_data = cls._get_cached_memory_facts(db)

        doc_items = cached_doc_data["items"]
        doc_matrix = cached_doc_data["matrix"]
        doc_norms = cached_doc_data["norms"]

        mem_items = cached_mem_data["items"]
        mem_matrix = cached_mem_data["matrix"]
        mem_norms = cached_mem_data["norms"]

        # Strict document filtering
        if document_id and document_id != "memory":
            target = document_id.lower().strip()
            indices = [
                i for i, it in enumerate(doc_items)
                if it["document_id"] == document_id or it["filename"].lower() == target or target in it["filename"].lower()
            ]
            items = [doc_items[i] for i in indices]
            if indices:
                sub_matrix = doc_matrix[indices]
                sub_norms = doc_norms[indices]
            else:
                sub_matrix = np.empty((0, 384), dtype=np.float32)
                sub_norms = np.empty((0,), dtype=np.float32)
        elif document_id == "memory":
            items = list(mem_items)
            sub_matrix = mem_matrix
            sub_norms = mem_norms
        else:
            items = list(doc_items) + list(mem_items)
            if len(doc_items) > 0 and len(mem_items) > 0:
                sub_matrix = np.vstack([doc_matrix, mem_matrix])
                sub_norms = np.concatenate([doc_norms, mem_norms])
            elif len(doc_items) > 0:
                sub_matrix = doc_matrix
                sub_norms = doc_norms
            else:
                sub_matrix = mem_matrix
                sub_norms = mem_norms

        if not items:
            return []

        # 1. Vector Cosine Similarity
        q_arr = np.array(query_vec, dtype=np.float32)
        norm_q = float(np.linalg.norm(q_arr))
        if norm_q == 0:
            norm_q = 1e-9

        q_norm_arr = q_arr / norm_q
        dense_sims = (sub_matrix @ q_norm_arr) / sub_norms
        dense_sims = np.clip(dense_sims, 0.0, 1.0)

        # 2. Okapi BM25 Lexical Score
        search_query = expanded_query or query
        bm25_scores = compute_bm25_scores(search_query, items)
        max_bm25 = max(bm25_scores) if bm25_scores and max(bm25_scores) > 0 else 1.0

        # 3. Reciprocal Rank Fusion (RRF) & Hybrid Score Fusion
        dense_ranks = np.argsort(-dense_sims)
        dense_rank_map = {idx: r for r, idx in enumerate(dense_ranks)}

        bm25_arr = np.array(bm25_scores, dtype=np.float32)
        bm25_ranks = np.argsort(-bm25_arr)
        bm25_rank_map = {idx: r for r, idx in enumerate(bm25_ranks)}

        scored = []
        k_rrf = 40.0
        w_dense = 0.55
        w_bm25 = 0.45

        for idx, it in enumerate(items):
            vec_sim = float(dense_sims[idx])
            bm25_s = float(bm25_scores[idx])
            norm_bm25 = bm25_s / max_bm25 if max_bm25 > 0 else 0.0

            r_dense = dense_rank_map.get(idx, len(items))
            r_bm25 = bm25_rank_map.get(idx, len(items))

            # Reciprocal Rank Fusion
            rrf_score = (w_dense / (k_rrf + r_dense)) + (w_bm25 / (k_rrf + r_bm25))

            # Hybrid linear blend for calibration
            hybrid_score = (vec_sim * 0.6) + (norm_bm25 * 0.4)

            # Prioritize memory/correction items slightly
            if it.get("is_memory"):
                rrf_score += 0.015
                hybrid_score = min(1.0, hybrid_score + 0.08)
                vec_sim = min(1.0, vec_sim + 0.05)

            # No hard drop-off threshold: keep all positive or top-ranked matches
            scored.append({
                "chunk_id": it["chunk_id"],
                "document_id": it["document_id"],
                "filename": it["filename"],
                "format": it["format"],
                "s3_url": it["s3_url"],
                "chunk_index": it["chunk_index"],
                "heading": it["heading"],
                "content": it["content"],
                "similarity_score": round(float(hybrid_score), 4),
                "vector_score": round(float(vec_sim), 4),
                "bm25_score": round(float(bm25_s), 4),
                "rrf_score": float(rrf_score),
                "distance": round(1.0 - vec_sim, 4),
                "source_type": it.get("source_type", "document"),
                "fact_type": it.get("fact_type")
            })

        # Rank by RRF Score descending
        scored.sort(key=lambda x: (x["rrf_score"], x["similarity_score"]), reverse=True)
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
        Sub-millisecond retrieval of top learned facts/rules/corrections from in-memory cache.
        """
        try:
            cached_mem = cls._get_cached_memory_facts(db)
            raw_facts = cached_mem["raw_facts"]
            if not raw_facts:
                return []

            query_vec = cls.generate_single_embedding(query)
            import numpy as np

            q_vec = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q_vec))
            if q_norm == 0:
                q_norm = 1e-9

            # In-memory matrix multiplication
            f_mat = cached_mem["matrix"]
            f_norms = cached_mem["norms"]
            sim_arr = (f_mat @ (q_vec / q_norm)) / f_norms

            scored = []
            q_words = set(re.findall(r'\w+', query.lower()))

            for idx, f in enumerate(raw_facts):
                sim = max(0.0, float(sim_arr[idx]))
                f_words = set(re.findall(r'\w+', (f.content or '').lower()))
                overlap = len(q_words & f_words)
                combined_score = sim + (0.1 * min(overlap, 3))

                if combined_score > 0.30 or overlap >= 1:
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

        cls._invalidate_memory_facts_cache()

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
            # Use the user's original question as subject for better retrieval similarity
            # Find the user message that preceded this AI message
            user_question = ""
            try:
                prev_user_msg = db.query(RagChatMessage).filter(
                    RagChatMessage.session_id == msg.session_id,
                    RagChatMessage.role == "user",
                    RagChatMessage.created_at < msg.created_at
                ).order_by(RagChatMessage.created_at.desc()).first()
                if prev_user_msg:
                    user_question = prev_user_msg.content[:80]
            except Exception:
                user_question = ""

            subject_label = f"Koreksi untuk: {user_question}" if user_question else f"Koreksi: {msg.content[:40]}..."
            learned_fact = cls.learn_fact(
                db=db,
                content=correction_text.strip(),
                subject=subject_label,
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
    def get_learned_facts(
        cls,
        db: Session,
        user_id: Optional[int] = None,
        limit: int = 100,
        fact_type: Optional[str] = None,
        learned_from: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves learned long-term memory facts with optional filters."""
        q = db.query(RagMemoryFact).filter(RagMemoryFact.is_active == True)
        if fact_type:
            q = q.filter(RagMemoryFact.fact_type == fact_type)
        if learned_from:
            q = q.filter(RagMemoryFact.learned_from == learned_from)
        facts = q.order_by(RagMemoryFact.created_at.desc()).limit(limit).all()

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
            cls._invalidate_memory_facts_cache()
            return True
        return False

    @classmethod
    def delete_learned_facts_bulk(cls, db: Session, fact_ids: List[str]) -> int:
        """Bulk-deletes multiple learned facts by their IDs."""
        if not fact_ids:
            return 0
        deleted = db.query(RagMemoryFact).filter(
            RagMemoryFact.id.in_(fact_ids)
        ).delete(synchronize_session=False)
        db.commit()
        cls._invalidate_memory_facts_cache()
        logger.info(f"[RagService] Bulk deleted {deleted} memory facts.")
        return deleted

    @classmethod
    def cleanup_old_chat_sessions(cls, db: Session, days: int = 7) -> Dict[str, int]:
        """
        Auto-cleanup: Permanently deletes chat sessions (and their messages via CASCADE)
        that are older than `days` days. Also removes associated auto_chat memory facts.
        Called by the daily background scheduler.
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            # Find old session IDs first
            old_sessions = db.query(RagChatSession).filter(
                RagChatSession.updated_at < cutoff
            ).all()
            old_session_ids = [s.id for s in old_sessions]

            deleted_sessions = 0
            deleted_facts = 0

            if old_session_ids:
                # Delete auto_chat memory facts linked to these old sessions
                deleted_facts = db.query(RagMemoryFact).filter(
                    RagMemoryFact.source_session_id.in_(old_session_ids),
                    RagMemoryFact.learned_from == "auto_chat"
                ).delete(synchronize_session=False)

                # Delete sessions (messages are cascade-deleted)
                deleted_sessions = db.query(RagChatSession).filter(
                    RagChatSession.id.in_(old_session_ids)
                ).delete(synchronize_session=False)

                db.commit()

            logger.info(
                f"[RagService] Auto-cleanup (>{days}d): "
                f"deleted {deleted_sessions} sessions, {deleted_facts} auto-chat facts."
            )
            return {"deleted_sessions": deleted_sessions, "deleted_facts": deleted_facts}
        except Exception as e:
            db.rollback()
            logger.error(f"[RagService] cleanup_old_chat_sessions error: {e}", exc_info=True)
            return {"deleted_sessions": 0, "deleted_facts": 0}

    @classmethod
    def chat_completion(
        cls,
        db: Session,
        query: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        top_k: int = 5,
        document_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None,
        user_id: Optional[int] = None,
        enable_rerank: bool = True
    ) -> Dict[str, Any]:
        """
        RAG Chat Completion with Multi-Turn Persistent Memory (Redis + PostgreSQL), Two-Stage Reranking & Self-Growth:
        1. Retrieves session conversation history from Redis L1 cache or PostgreSQL L2 database.
        2. Retrieves top-k most relevant Markdown chunks via 2-stage vector search + ONNX Cross-Encoder reranking.
        3. Retrieves dynamic learned facts & user corrections from RagMemoryFact.
        4. Injects rich context and learned facts into LLM.
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

        # 4. Retrieve relevant chunks from documents (with bilingual expansion & 2-stage Cross-Encoder reranking)
        chunks = cls.search_similar_chunks(db, search_query, top_k=top_k, document_id=document_id, enable_rerank=enable_rerank)
        if not chunks and search_query != query.strip():
            chunks = cls.search_similar_chunks(db, query.strip(), top_k=top_k, document_id=document_id, enable_rerank=enable_rerank)

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
                "similarity_score": c.get("similarity_score", 0.0),
                "reranker_score": c.get("reranker_score"),
                "vector_score": c.get("vector_score"),
                "raw_reranker_logit": c.get("raw_reranker_logit"),
                "source_type": c.get("source_type", "document"),
                "fact_type": c.get("fact_type"),
                "content_preview": c.get("content", "")[:250]
            })

        combined_context = "\n\n---\n\n".join(context_parts) if context_parts else "Tidak ada dokumen yang relevan ditemukan di basis pengetahuan."

        # 7. Formulate System Prompt & Multi-Turn Message History
        system_instruction = custom_system_prompt or (
            "Anda adalah Hero Assistant, asisten AI resmi yang cerdas, komprehensif, dan profesional dalam bidang rekayasa teknis, spesifikasi ban (OTR / Earthmover / Radial / Bias), dan standar operasional keselamatan.\n\n"
            "ATURAN WAJIB FORMAT & AKURASI JAWABAN (STRICT RULES):\n"
            "1. BAHASA & PEMAHAMAN DWIBAHASA (CODE-MIXING):\n"
            "   - Pengguna sering bertanya menggunakan campuran Bahasa Indonesia dan istilah teknis Bahasa Inggris (misal: 'cold pressure', 'payload', 'inflation', 'rim width', 'load capacity', 'tread depth').\n"
            "   - Anda WAJIB memahami kueri campuran tersebut dan mencocokkannya dengan data pada Konteks Dokumen Pengetahuan (yang mungkin berbahasa Inggris).\n"
            "   - Sampaikan seluruh jawaban akhir dalam Bahasa Indonesia yang baku, terstruktur, komprehensif, dan profesional. Nama merek/model, kode ukuran (contoh: 27.00R49), kode TRA (contoh: E-4, L-5), dan simbol satuan tetap ditulis dalam format standar aslinya.\n"
            "2. AKURASI TINGGI PADA DATA SPESIFIKASI & TEKANAN ANGIN (PRESSURE):\n"
            "   - Teliti setiap kolom pada tabel Markdown dalam konteks secara presisi.\n"
            "   - Bedakan dengan tegas antara satuan Tekanan (Bar vs PSI vs kPa), Ukuran Rim (inch), Kapasitas Beban (kg vs lbs), dan Kecepatan (km/h).\n"
            "   - Jangan pernah tertukar antara nilai Tekanan dalam Bar (misal: 7.00 bar) dengan nilai dalam PSI (misal: 102 psi) atau ukuran velg/rim.\n"
            "   - Jika terdapat rekomendasi 'Cold Inflation Pressure' (tekanan dingin) atau variasi tekanan berdasarkan beban (payload) / aplikasi kerja (haulage vs loading), sebutkan secara terperinci.\n"
            "3. WAJIB TABEL MARKDOWN UNTUK DATA SPESIFIKASI/TABULAR:\n"
            "   - Jika jawaban memuat data spesifikasi ban, ukuran, tekanan angin, beban muatan, kecepatan, dimensi, atau perbandingan tipe ban, ANDA WAJIB MENYAJIKANNYA DALAM TABEL MARKDOWN LENGKAP & RAPI:\n"
            "     | Model / Tipe | Ukuran Ban | Star / PR | Rim Width | Cold Pressure (Bar) | Cold Pressure (PSI) | Max Load (kg) |\n"
            "     | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
            "     | ... | ... | ... | ... | ... | ... | ... |\n"
            "   - Untuk prosedur teknis, langkah keselamatan (SOP), atau pembongkaran/pemasangan, gunakan poin-poin bertahap (numbered/bullet points) yang rapi, berurutan, dan jelas.\n"
            "4. PRIORITAS MEMORI & KOREKSI PENGGUNA (TERTINGGI):\n"
            "   - Jika terdapat bagian '[Memori & Aturan Khusus yang Dipelajari dari Pengguna]' dalam konteks, Anda WAJIB memprioritaskan informasi tersebut di atas dokumen standar. Jangan pernah mengabaikan memori atau koreksi ini.\n"
            "5. JANGAN PREMATUR MENYATAKAN 'TIDAK TAHU':\n"
            "   - Jika tabel atau cuplikan teks di dalam Konteks memuat data model/ukuran/spesifikasi yang ditanyakan, Anda WAJIB menganalisis dan menjawabnya secara lengkap dari data tersebut.\n"
            "   - Hanya nyatakan informasi belum tercatat jika memang tidak ada data relevan sama sekali di dalam dokumen maupun memori.\n"
            "6. HANYA JAWABAN AKHIR (NO META-THOUGHTS / NO INTERNAL CHECKLIST):\n"
            "   - Langsung berikan penjelasan dan jawaban akhir yang bersih, informatif, dan mudah dipahami tanpa menyertakan catatan evaluasi aturan internal atau proses berpikir mentah."
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

        # Chat history is persisted in RagChatMessage/Redis; long-term memory is only saved on user feedback/correction

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
        Invokes LLM with full conversation messages list with persistent connection pooling.
        Priority:
        1. Groq (Ultra-fast LPU: ~300-600ms latency)
        2. Google Gemini API (Gemini 2.0 Flash: ~800ms)
        3. OpenRouter Fallback
        """
        session = get_http_session()

        # 1. Groq (Ultra-Fast LPU Engine)
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b").strip()

        if groq_key:
            try:
                payload = {
                    "model": groq_model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 2048,
                }
                groq_reasoning_models = ["deepseek", "qwq", "r1"]
                if any(rm in groq_model.lower() for rm in groq_reasoning_models):
                    payload["reasoning_format"] = "hidden"

                resp = session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=25
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return RagService._clean_llm_response(content)
                else:
                    logger.warning(f"[RagService] Groq error {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                logger.error(f"[RagService] Groq call exception: {e}")

        # 2. OpenRouter Fallback
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        openrouter_model = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free").strip()
        if openrouter_key:
            try:
                resp = session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://vision.chitrapratama.com",
                        "X-Title": "Hero Assistant RAG"
                    },
                    json={
                        "model": openrouter_model,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 2048
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return RagService._clean_llm_response(content)
                else:
                    logger.warning(f"[RagService] OpenRouter error {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                logger.error(f"[RagService] OpenRouter call exception: {e}")

        # 3. Google Gemini Fallback
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                gemini_text = "\n\n".join([f"[{m['role'].upper()}]: {m['content']}" for m in messages])
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=gemini_text
                )
                if response and response.text:
                    return RagService._clean_llm_response(response.text)
            except Exception as e:
                logger.error(f"[RagService] Gemini call exception: {e}")

        logger.error("[RagService] All LLM providers failed. Returning fallback message.")
        return (
            "⚠️ **Catatan Sistem:** Semua LLM provider (Groq, OpenRouter, Gemini) gagal merespons. "
            "Periksa log backend untuk detail error.\n\n"
            "Potongan dokumen yang relevan dari pgvector tetap tersedia di panel sumber di bawah."
        )
