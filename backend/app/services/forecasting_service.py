import logging
import re
import threading
from datetime import date, datetime
from typing import Any, Dict, List

import numpy as np
from sqlalchemy import create_engine, text

from .rag_datasource_service import RagDatasourceService

logger = logging.getLogger("rarayvision.forecasting")
_MODEL = None
_MODEL_LOCK = threading.Lock()
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value or ""):
        raise ValueError(f"Identifier database tidak valid: {value}")
    return f'"{value}"'


def _engine(db_url: str):
    if not db_url or not db_url.strip():
        raise ValueError("Database URL wajib diisi.")
    return create_engine(
        RagDatasourceService._normalize_db_url(db_url),
        connect_args={"connect_timeout": 7},
        pool_pre_ping=True,
    )


def _json_value(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def inspect_schema(db_url: str) -> Dict[str, Any]:
    result = RagDatasourceService.introspect_schema(db_url)
    if not result.get("success"):
        raise ValueError(result.get("message", "Schema database tidak dapat dibaca."))
    return {"tables": result.get("tables", [])}


def _load_series(
    db_url: str,
    table_name: str,
    time_column: str,
    value_column: str,
    limit: int,
) -> List[Dict[str, Any]]:
    table = _quote_identifier(table_name)
    time_col = _quote_identifier(time_column)
    value_col = _quote_identifier(value_column)
    query = text(
        f"SELECT {time_col} AS timestamp, {value_col} AS value "
        f"FROM \"public\".{table} "
        f"WHERE {time_col} IS NOT NULL AND {value_col} IS NOT NULL "
        f"ORDER BY {time_col} ASC LIMIT :limit"
    )
    with _engine(db_url).connect() as connection:
        rows = connection.execute(query, {"limit": min(max(limit, 8), 8192)}).mappings().all()

    series = []
    for row in rows:
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            series.append({"timestamp": _json_value(row["timestamp"]), "value": value})
    return series


def _get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            import torch
            import timesfm
        except ImportError as exc:
            raise RuntimeError(
                "TimesFM belum terpasang. Jalankan `pip install -r requirements.txt` "
                "lalu restart backend."
            ) from exc

        model_class = getattr(timesfm, "TimesFM_2p5_200M_torch", None)
        if model_class is None:
            from timesfm.timesfm_2p5.timesfm_2p5_torch import TimesFM_2p5_200M_torch

            model_class = TimesFM_2p5_200M_torch

        logger.info("Loading TimesFM 2.5 checkpoint...")
        torch.set_float32_matmul_precision("high")
        model = model_class.from_pretrained(
            "google/timesfm-2.5-200m-pytorch",
            torch_compile=False,
        )
        model.compile(
            timesfm.ForecastConfig(
                max_context=2048,
                max_horizon=256,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=False,
                fix_quantile_crossing=True,
            )
        )
        _MODEL = model
        return _MODEL


def forecast(
    db_url: str,
    table_name: str,
    time_column: str,
    value_column: str,
    horizon: int,
    context_length: int,
) -> Dict[str, Any]:
    horizon = min(max(int(horizon), 1), 256)
    context_length = min(max(int(context_length), 8), 2048)
    rows = _load_series(db_url, table_name, time_column, value_column, 8192)
    if len(rows) < 8:
        raise ValueError("Minimal 8 baris numerik diperlukan untuk forecasting.")

    context = np.asarray([row["value"] for row in rows[-context_length:]], dtype=np.float32)
    try:
        model = _get_model()
        with _MODEL_LOCK:
            point_forecast, quantile_forecast = model.forecast(
                horizon=horizon,
                inputs=[context],
            )
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("TimesFM forecast failed")
        raise RuntimeError(f"TimesFM gagal memproses data: {exc}") from exc

    last_timestamp = rows[-1]["timestamp"]
    predictions = []
    for index, value in enumerate(point_forecast[0].tolist(), start=1):
        quantiles = quantile_forecast[0][index - 1].tolist() if quantile_forecast is not None else []
        predictions.append({
            "step": index,
            "forecast": float(value),
            "p10": float(quantiles[1]) if len(quantiles) > 1 else None,
            "p50": float(quantiles[5]) if len(quantiles) > 5 else None,
            "p90": float(quantiles[9]) if len(quantiles) > 9 else None,
        })

    return {
        "model": "TimesFM 2.5 200M",
        "table": table_name,
        "time_column": time_column,
        "value_column": value_column,
        "rows_used": len(context),
        "horizon": horizon,
        "last_timestamp": last_timestamp,
        "history": rows[-min(len(rows), 100):],
        "predictions": predictions,
    }
