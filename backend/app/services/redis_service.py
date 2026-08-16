import os
import json
import time
import hashlib
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("rarayvision.redis")

_redis_client = None
_redis_initialized = False


class RedisService:
    """
    High-Performance Redis Manager for Raray Vision:
    1. Multi-turn Chat Conversation Session Memory (persisted & fast retrieval)
    2. RAG Semantic Search & LLM Query Cache (<5ms response time)
    3. Fast Embedding Vector Cache (avoids ONNX recomputations)
    """

    @classmethod
    def get_client(cls):
        global _redis_client, _redis_initialized
        if _redis_client is not None:
            return _redis_client

        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            logger.info("[RedisService] REDIS_URL not configured. Redis memory cache disabled.")
            return None

        try:
            import redis
            _redis_client = redis.from_url(
                redis_url,
                socket_timeout=3,
                socket_connect_timeout=3,
                decode_responses=True,
                retry_on_timeout=True
            )
            # Test ping
            _redis_client.ping()
            _redis_initialized = True
            logger.info("[RedisService] Successfully connected to Redis server.")
            return _redis_client
        except Exception as e:
            logger.warning(f"[RedisService] Failed to connect to Redis: {e}. Fallback to in-memory mode.")
            _redis_client = None
            return None

    @classmethod
    def is_available(cls) -> bool:
        client = cls.get_client()
        if not client:
            return False
        try:
            return client.ping()
        except Exception:
            return False

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns Redis health status and performance statistics."""
        client = cls.get_client()
        if not client:
            return {
                "available": False,
                "status": "disabled",
                "message": "Redis is not connected or REDIS_URL is not set."
            }
        try:
            start_t = time.perf_counter()
            client.ping()
            ping_ms = round((time.perf_counter() - start_t) * 1000, 2)
            info = client.info()
            return {
                "available": True,
                "status": "connected",
                "ping_ms": ping_ms,
                "version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "total_system_memory_human": info.get("total_system_memory_human")
            }
        except Exception as e:
            return {
                "available": False,
                "status": "error",
                "message": str(e)
            }

    # ==========================================
    # 1. Multi-Turn Chat Conversation Memory
    # ==========================================

    @classmethod
    def save_chat_turn(
        cls,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        ttl_seconds: int = 86400 # 24 Hours
    ) -> bool:
        """Appends a user/assistant turn to Redis session list with TTL."""
        client = cls.get_client()
        if not client or not session_id:
            return False

        key = f"rag:session:{session_id}:messages"
        payload = {
            "role": role,
            "content": content,
            "sources": sources or [],
            "timestamp": time.time()
        }

        try:
            client.rpush(key, json.dumps(payload))
            # Keep maximum 30 messages per session
            client.ltrim(key, -30, -1)
            client.expire(key, ttl_seconds)
            return True
        except Exception as e:
            logger.warning(f"[RedisService] Failed to save chat turn: {e}")
            return False

    @classmethod
    def get_chat_history(cls, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves last N turns from Redis session memory."""
        client = cls.get_client()
        if not client or not session_id:
            return []

        key = f"rag:session:{session_id}:messages"
        try:
            raw_items = client.lrange(key, -limit, -1)
            history = []
            for item in raw_items:
                try:
                    history.append(json.loads(item))
                except Exception:
                    pass
            return history
        except Exception as e:
            logger.warning(f"[RedisService] Failed to get chat history: {e}")
            return []

    @classmethod
    def clear_chat_history(cls, session_id: str) -> bool:
        """Deletes session conversation history."""
        client = cls.get_client()
        if not client or not session_id:
            return False

        key = f"rag:session:{session_id}:messages"
        try:
            client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"[RedisService] Failed to clear chat history: {e}")
            return False

    # ==========================================
    # 2. RAG Semantic Query Caching (<5ms)
    # ==========================================

    @classmethod
    def get_rag_cache(cls, query: str, document_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves cached RAG response for identical semantic queries."""
        client = cls.get_client()
        if not client:
            return None

        norm_query = query.strip().lower()
        key_hash = hashlib.md5(f"{norm_query}:{document_id or 'all'}".encode("utf-8")).hexdigest()
        key = f"rag:cache:query:{key_hash}"

        try:
            cached = client.get(key)
            if cached:
                data = json.loads(cached)
                data["from_cache"] = True
                return data
        except Exception as e:
            logger.warning(f"[RedisService] Cache read error: {e}")
        return None

    @classmethod
    def set_rag_cache(
        cls,
        query: str,
        document_id: Optional[str],
        response_data: Dict[str, Any],
        ttl_seconds: int = 1800 # 30 Minutes
    ) -> bool:
        """Caches RAG response in Redis."""
        client = cls.get_client()
        if not client:
            return False

        norm_query = query.strip().lower()
        key_hash = hashlib.md5(f"{norm_query}:{document_id or 'all'}".encode("utf-8")).hexdigest()
        key = f"rag:cache:query:{key_hash}"

        try:
            # Don't cache error responses
            if "❌" in str(response_data.get("answer", "")):
                return False

            client.setex(key, ttl_seconds, json.dumps(response_data))
            return True
        except Exception as e:
            logger.warning(f"[RedisService] Cache write error: {e}")
            return False
