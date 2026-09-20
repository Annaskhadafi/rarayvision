"""Small stdlib contract check for request-scoped RAG provider selection."""
import os
import unittest
from unittest.mock import patch

from backend.app.services.rag_service import RagService


class ProviderSelectionTest(unittest.TestCase):
    def setUp(self):
        self.env = {key: os.environ.get(key) for key in (
            "OPENAI_API_KEY", "OPENAI_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
            "GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "LLM_PROVIDER"
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


if __name__ == "__main__":
    unittest.main()
