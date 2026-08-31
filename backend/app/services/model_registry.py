"""
model_registry.py — Centralized AI/ML Model Registry for Raray Vision

This module provides a global registry of all AI/ML/CV models in the system.
Each model can be loaded/unloaded on-demand to conserve RAM.
Models that are unloaded will not consume RAM and services will return a clear
503 error indicating the model needs to be activated first.
"""

import gc
import time
import threading
from typing import Callable, Dict, Any, Optional

# ------------------------------------------------------------------ #
# Global registry state                                                 #
# ------------------------------------------------------------------ #
_registry: Dict[str, Dict[str, Any]] = {}
_registry_lock = threading.Lock()


def register_model(
    model_id: str,
    name: str,
    description: str,
    category: str,
    ram_estimate_mb: int,
    load_fn: Callable,
    unload_fn: Callable,
    auto_loaded: bool = False,
    icon: str = "🤖",
):
    """Register a model into the global registry."""
    with _registry_lock:
        _registry[model_id] = {
            "id": model_id,
            "name": name,
            "description": description,
            "category": category,
            "ram_estimate_mb": ram_estimate_mb,
            "load_fn": load_fn,
            "unload_fn": unload_fn,
            "loaded": False,
            "loading": False,
            "icon": icon,
            "loaded_at": None,
            "load_time_ms": None,
            "error": None,
        }
        # If model is already in RAM at startup, mark it
        if auto_loaded:
            _registry[model_id]["loaded"] = True
            _registry[model_id]["loaded_at"] = time.time()


def load_model(model_id: str) -> Dict[str, Any]:
    """Load a model into RAM. Returns updated status."""
    with _registry_lock:
        if model_id not in _registry:
            return {"success": False, "error": f"Model '{model_id}' not found in registry"}
        entry = _registry[model_id]
        if entry["loaded"]:
            return {"success": True, "message": "Model already loaded", "model_id": model_id}
        if entry["loading"]:
            return {"success": False, "error": "Model is currently loading, please wait"}
        entry["loading"] = True
        entry["error"] = None

    try:
        t0 = time.time()
        entry["load_fn"]()
        elapsed_ms = round((time.time() - t0) * 1000)
        with _registry_lock:
            entry["loaded"] = True
            entry["loading"] = False
            entry["loaded_at"] = time.time()
            entry["load_time_ms"] = elapsed_ms
        return {
            "success": True,
            "model_id": model_id,
            "load_time_ms": elapsed_ms,
            "message": f"Model '{entry['name']}' loaded successfully in {elapsed_ms}ms"
        }
    except Exception as e:
        err_msg = str(e)
        with _registry_lock:
            entry["loaded"] = False
            entry["loading"] = False
            entry["error"] = err_msg
        return {"success": False, "model_id": model_id, "error": err_msg}


def unload_model(model_id: str) -> Dict[str, Any]:
    """Unload a model from RAM and trigger GC."""
    with _registry_lock:
        if model_id not in _registry:
            return {"success": False, "error": f"Model '{model_id}' not found"}
        entry = _registry[model_id]
        if not entry["loaded"]:
            return {"success": True, "message": "Model already unloaded", "model_id": model_id}

    try:
        entry["unload_fn"]()
        gc.collect()
        with _registry_lock:
            entry["loaded"] = False
            entry["loaded_at"] = None
            entry["error"] = None
        return {
            "success": True,
            "model_id": model_id,
            "message": f"Model '{entry['name']}' unloaded from RAM. GC triggered."
        }
    except Exception as e:
        err_msg = str(e)
        with _registry_lock:
            entry["error"] = err_msg
        return {"success": False, "model_id": model_id, "error": err_msg}


def get_all_models() -> list:
    """Returns all registered model statuses (without internal callables)."""
    with _registry_lock:
        result = []
        for model_id, entry in _registry.items():
            result.append({
                "id": entry["id"],
                "name": entry["name"],
                "description": entry["description"],
                "category": entry["category"],
                "ram_estimate_mb": entry["ram_estimate_mb"],
                "loaded": entry["loaded"],
                "loading": entry["loading"],
                "icon": entry["icon"],
                "loaded_at": entry["loaded_at"],
                "load_time_ms": entry["load_time_ms"],
                "error": entry["error"],
            })
        return result


def get_model_status(model_id: str) -> Optional[Dict[str, Any]]:
    """Returns status of a single model."""
    with _registry_lock:
        entry = _registry.get(model_id)
        if not entry:
            return None
        return {
            "id": entry["id"],
            "name": entry["name"],
            "loaded": entry["loaded"],
            "loading": entry["loading"],
            "error": entry["error"],
        }


def is_model_loaded(model_id: str) -> bool:
    """Quick check if a model is currently loaded."""
    with _registry_lock:
        return _registry.get(model_id, {}).get("loaded", False)


def load_all_models() -> Dict[str, Any]:
    """Load all registered models."""
    results = {}
    with _registry_lock:
        ids = list(_registry.keys())
    for model_id in ids:
        results[model_id] = load_model(model_id)
    return results


def unload_all_models() -> Dict[str, Any]:
    """Unload all registered models from RAM."""
    results = {}
    with _registry_lock:
        ids = list(_registry.keys())
    for model_id in ids:
        results[model_id] = unload_model(model_id)
    gc.collect()
    return results
