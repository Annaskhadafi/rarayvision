"""Small stdlib contract checks for RAG provider and reranker selection."""
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from backend.app.services.rag_service import RagService, _repair_mojibake
from backend.app.services.redis_service import RedisService


class ProviderSelectionTest(unittest.TestCase):
    def setUp(self):
        self.env = {key: os.environ.get(key) for key in (
            "OPENAI_API_KEY", "OPENAI_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
            "GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "LLM_PROVIDER",
            "RERANKER_MODE", "JEV_MODEL", "JEV_TIMEOUT_SECONDS", "LLM_DISABLE_REASONING"
        )}
        for key in self.env:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_allowlist_configuration_and_safe_metadata(self):
        os.environ["OPENROUTER_API_KEY"] = "test-secret"
        os.environ["OPENROUTER_MODEL"] = "test-model"
        self.assertIsNone(RagService._resolve_provider("  "))
        self.assertEqual(RagService._resolve_provider("openrouter"), "openrouter")
        with self.assertRaises(ValueError):
            RagService._resolve_provider("unknown")
        with self.assertRaises(ValueError):
            RagService._resolve_provider("openai")
        with patch("backend.app.services.rag_service.get_reranker_model", return_value=None):
            info = RagService.get_embedding_info()
        providers = {item["id"]: item for item in info["llm_providers"]}
        self.assertTrue(providers["openrouter"]["configured"])
        self.assertEqual(providers["openrouter"]["model"], "test-model")
        self.assertNotIn("test-secret", repr(info))

    def test_explicit_failure_is_not_cached_and_can_recover(self):
        os.environ["OPENROUTER_API_KEY"] = "test-secret"
        class Response:
            def __init__(self, status, content="ok"):
                self.status_code, self._content = status, content
                self.text = "upstream failure" if status != 200 else ""
            def json(self):
                return {"choices": [{"message": {"content": self._content}}]}
        class Session:
            responses = iter((Response(503), Response(200, "recovered")))
            def post(self, *args, **kwargs):
                return next(self.responses)
        with patch("backend.app.services.rag_service.get_http_session", return_value=Session()), \
             patch("backend.app.services.rag_service.RedisService.set_rag_cache") as cache_write:
            with self.assertRaises(RuntimeError):
                RagService._call_llm_messages([{"role": "user", "content": "hi"}], "openrouter")
            self.assertEqual(RagService._call_llm_messages([{"role": "user", "content": "hi"}], "openrouter"), "recovered")
            cache_write.assert_not_called()

    def test_jev_reranker_uses_decisions_endpoint_and_sorts_scores(self):
        os.environ["OPENROUTER_API_KEY"] = "test-secret"
        captured = {}

        class Response:
            status_code = 200
            text = ""
            def json(self):
                return {
                    "answers": {
                        "chunk_0": {"score": 1, "confidence": 0.8},
                        "chunk_1": {"score": 4, "confidence": 0.9},
                    }
                }

        class Session:
            def post(self, url, **kwargs):
                captured["url"] = url
                captured["json"] = kwargs["json"]
                return Response()

        chunks = [
            {"filename": "a.md", "content": "weak", "similarity_score": 0.7},
            {"filename": "b.md", "content": "direct answer", "similarity_score": 0.6},
        ]
        with patch("backend.app.services.rag_service.get_http_session", return_value=Session()):
            result = RagService.rerank_chunks("query", chunks, top_k=2, mode="jev")
        self.assertEqual(captured["url"], "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(captured["json"]["model"], "typesafe/jev-1.13")
        self.assertEqual(result[0]["filename"], "b.md")
        self.assertEqual(result[0]["reranker_score"], 1.0)

    def test_local_mode_never_calls_remote_reranker(self):
        chunks = [
            {"filename": "a.md", "content": "a", "similarity_score": 0.7},
            {"filename": "b.md", "content": "b", "similarity_score": 0.6},
        ]

        class LocalReranker:
            def rerank(self, query, texts):
                return [0.1, 0.9]

        with patch("backend.app.services.rag_service.get_reranker_model", return_value=LocalReranker()), \
             patch.object(RagService, "rerank_chunks_openrouter") as remote:
            result = RagService.rerank_chunks("query", chunks, top_k=2, mode="local_onnx")
        remote.assert_not_called()
        self.assertEqual(result[0]["filename"], "b.md")

    def test_openai_answer_payload_avoids_openrouter_reasoning_control(self):
        os.environ["OPENAI_API_KEY"] = "test-secret"
        os.environ["LLM_DISABLE_REASONING"] = "true"
        captured = {}

        class Response:
            status_code = 200
            text = ""
            def json(self):
                return {"choices": [{"message": {"content": "answer"}}]}

        class Session:
            def post(self, url, **kwargs):
                captured["json"] = kwargs["json"]
                return Response()

        with patch("backend.app.services.rag_service.get_http_session", return_value=Session()):
            self.assertEqual(
                RagService._call_llm_messages([{"role": "user", "content": "hi"}], "openai"),
                "answer",
            )
        self.assertNotIn("reasoning", captured["json"])

    def test_chat_parser_accepts_jsonl_and_sse(self):
        class Response:
            def __init__(self, text):
                self.text = text
            def json(self):
                raise ValueError("Extra data")

        jsonl = Response(
            '{"choices":[{"delta":{"content":"Halo "}}]}\n'
            '{"choices":[{"delta":{"content":"dunia"}}]}\n'
        )
        sse = Response(
            'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"B"}}]}\n'
            'data: [DONE]\n'
        )
        self.assertEqual(RagService._extract_chat_content(jsonl), "Halo dunia")
        self.assertEqual(RagService._extract_chat_content(sse), "AB")

    def test_local_embedding_model_is_not_sent_to_openrouter(self):
        os.environ["OPENROUTER_API_KEY"] = "test-secret"
        with patch("backend.app.services.rag_service.get_http_session") as get_session:
            self.assertIsNone(
                RagService.generate_embeddings_openrouter(["text"], model="BAAI/bge-small-en-v1.5")
            )
        get_session.assert_not_called()

    def test_mojibake_is_repaired_without_changing_clean_text(self):
        self.assertEqual(_repair_mojibake("Size: 12.00R24 â 700â¯kPa â"), "Size: 12.00R24 – 700 kPa ★")
        self.assertEqual(_repair_mojibake("Size: 12.00R24 - 700 kPa"), "Size: 12.00R24 - 700 kPa")

    def test_standalone_detection_ignores_only_opening_greeting(self):
        self.assertTrue(RagService._is_standalone_query([
            {"role": "assistant", "content": "Halo! Ada yang bisa saya bantu?"},
            {"role": "user", "content": "Apa prosedurnya?"},
        ], "Apa prosedurnya?"))
        self.assertFalse(RagService._is_standalone_query([
            {"role": "assistant", "content": "Halo! Ada yang bisa saya bantu?"},
            {"role": "user", "content": "Jelaskan tekanan ban."},
            {"role": "user", "content": "Apa prosedurnya?"},
        ], "Apa prosedurnya?"))

    def test_redis_chat_turn_uses_one_pipeline(self):
        class Pipeline:
            def __init__(self):
                self.commands = []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def rpush(self, *args):
                self.commands.append(("rpush", args))
            def ltrim(self, *args):
                self.commands.append(("ltrim", args))
            def expire(self, *args):
                self.commands.append(("expire", args))
            def execute(self):
                return self.commands

        class Client:
            def __init__(self):
                self.pipe = Pipeline()
            def pipeline(self):
                return self.pipe

        client = Client()
        with patch.object(RedisService, "get_client", return_value=client):
            self.assertTrue(RedisService.save_chat_turn("sess-test", "user", "hello"))
        self.assertEqual([name for name, _ in client.pipe.commands], ["rpush", "ltrim", "expire"])

    def test_cached_first_turn_is_persisted_to_requested_session(self):
        os.environ["OPENROUTER_API_KEY"] = "test-secret"
        cached = {"answer": "cached answer", "sources": [], "attached_images": []}
        saved = [SimpleNamespace(id="user-id"), SimpleNamespace(id="assistant-id")]
        with patch.object(RedisService, "get_chat_history", return_value=[]), \
             patch.object(RagService, "get_session_messages", return_value=[]), \
             patch.object(RedisService, "get_rag_cache", return_value=cached), \
             patch.object(RagService, "save_message_to_db", side_effect=saved) as save_message, \
             patch.object(RedisService, "save_chat_turn") as save_turn:
            result = RagService.chat_completion(
                db=None,
                query="Apa prosedurnya?",
                session_id="sess-new",
                provider="openrouter",
            )
        self.assertEqual(result["session_id"], "sess-new")
        self.assertEqual(result["user_message_id"], "user-id")
        self.assertEqual(result["assistant_message_id"], "assistant-id")
        self.assertEqual(save_message.call_count, 2)
        self.assertEqual(save_turn.call_count, 2)


if __name__ == "__main__":
    unittest.main()
