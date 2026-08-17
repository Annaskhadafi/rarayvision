import io
import csv
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.app.services.automl_service import AutoMLService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/automl", tags=["AutoML & AI Data Forecasting"])


class AnalyzeRequest(BaseModel):
    dataset_name: Optional[str] = Field("Dataset_API", description="Nama dataset atau konteks bisnis")
    data: List[Dict[str, Any]] = Field(..., description="Array of objects (data tabel JSON mentah)")
    target_column: Optional[str] = Field(None, description="Kolom target prediksi (opsional, jika kosong sistem auto-detect)")
    date_column: Optional[str] = Field(None, description="Kolom tanggal/waktu (opsional, jika kosong sistem auto-detect)")
    forecast_horizon: Optional[int] = Field(14, description="Jumlah periode ke depan yang ingin diproyeksikan")


@router.get("/presets", summary="Get Preset Datasets for Testing")
def get_presets():
    """
    Returns realistic sample datasets (Sales, Tire Demand, Attendance)
    for instant testing and demonstration.
    """
    return {
        "status": "success",
        "presets": AutoMLService.get_presets()
    }


@router.post("/analyze-and-predict", summary="Auto-Profile, Forecast, Detect Anomalies & Interpret with AI")
async def analyze_and_predict(payload: AnalyzeRequest, request: Request):
    """
    Universal AutoML Ingestion Endpoint:
    - Accepts raw tabular JSON array from any external website / API
    - Auto-profiles columns and infers task (Time-Series / Anomaly / Classification)
    - Performs statistical modeling, future projections & anomaly detection
    - Generates executive business interpretation via AI LLM
    - Returns structured charts, tables, and embeddable iframe widgets
    """
    try:
        base_url = str(request.base_url)
        result = AutoMLService.process_and_analyze(
            data=payload.data,
            dataset_name=payload.dataset_name,
            target_column=payload.target_column,
            date_column=payload.date_column,
            forecast_horizon=payload.forecast_horizon or 14,
            base_url=base_url
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[AutoMLController] Processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan saat memproses data: {str(e)}")


@router.post("/upload-csv", summary="Upload CSV File & Run AutoML Pipeline")
async def upload_csv_and_analyze(
    request: Request,
    file: UploadFile = File(..., description="CSV File containing tabular records"),
    dataset_name: Optional[str] = Form(None),
    target_column: Optional[str] = Form(None),
    date_column: Optional[str] = Form(None),
    forecast_horizon: int = Form(14)
):
    """
    Uploads a raw CSV file, parses it into tabular dicts, and runs full AutoML pipeline.
    """
    try:
        content = await file.read()
        text_content = content.decode("utf-8-sig", errors="replace")
        
        reader = csv.DictReader(io.StringIO(text_content))
        data_rows = list(reader)

        if not data_rows:
            raise HTTPException(status_code=400, detail="File CSV kosong atau tidak memiliki baris data valid.")

        base_url = str(request.base_url)
        name = dataset_name or file.filename.replace(".csv", "").replace("_", " ").title()

        result = AutoMLService.process_and_analyze(
            data=data_rows,
            dataset_name=name,
            target_column=target_column if target_column else None,
            date_column=date_column if date_column else None,
            forecast_horizon=forecast_horizon,
            base_url=base_url
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AutoMLController] CSV upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gagal memproses file CSV: {str(e)}")


@router.get("/widget/{job_id}", response_class=HTMLResponse, summary="Embeddable Iframe Widget")
def render_embed_widget(job_id: str):
    """
    Returns standalone, responsive HTML/JS view ready to be embedded
    into external websites using <iframe>.
    """
    html_content = AutoMLService.render_widget_html(job_id)
    return HTMLResponse(content=html_content, status_code=200)


@router.get("/results/{job_id}", summary="Get Cached Analysis Result")
def get_cached_result(job_id: str):
    """
    Retrieves previously processed result payload by job ID.
    """
    data = AutoMLService.get_widget_data(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Sesi hasil analitik tidak ditemukan.")
    return data
