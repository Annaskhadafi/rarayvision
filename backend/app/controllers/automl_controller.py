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


class SimulateScenarioRequest(BaseModel):
    job_id: str = Field(..., description="Job ID dari sesi analisis sebelumnya")
    growth_boost_pct: float = Field(0.0, description="Penyesuaian pertumbuhan permintaan dalam % (-50 hingga +100)")
    spike_date: Optional[str] = Field(None, description="Tanggal spesifik event/promo spike (YYYY-MM-DD)")
    spike_multiplier: float = Field(1.0, description="Pengali lonjakan pada tanggal event (contoh: 1.5 untuk +50%)")
    safety_buffer_days: int = Field(0, description="Jumlah hari buffer persediaan/safety stock yang direkomendasikan")


class FetchExternalApiRequest(BaseModel):
    api_url: str = Field(..., description="URL endpoint API eksternal yang mengembalikan data JSON")
    method: Optional[str] = Field("GET", description="HTTP Method (GET / POST)")
    headers: Optional[Dict[str, str]] = Field(None, description="Header kustom seperti Authorization Bearer token")
    request_body: Optional[Dict[str, Any]] = Field(None, description="Payload body jika POST")
    data_path: Optional[str] = Field(None, description="Key path jika data terbungkus (misal: 'data' atau 'items')")
    dataset_name: Optional[str] = Field(None, description="Nama dataset")
    target_column: Optional[str] = Field(None, description="Kolom target nilai numerik")
    date_column: Optional[str] = Field(None, description="Kolom tanggal/waktu")
    forecast_horizon: Optional[int] = Field(14, description="Jumlah periode proyeksi masa depan")


class AskAiRequest(BaseModel):
    job_id: str = Field(..., description="Job ID dari sesi dataset analitik yang sedang dibuka")
    question: str = Field(..., description="Pertanyaan analisis pengguna seputar data ini")
    chat_history: Optional[List[Dict[str, str]]] = Field(None, description="Riwayat percakapan sebelumnya")


@router.post("/fetch-external-api", summary="Fetch Tabular Data from External API URL & Run AutoML")
async def fetch_external_api(payload: FetchExternalApiRequest, request: Request):
    """
    Direct External API Ingestion:
    Fetches raw JSON data from any 3rd party URL (ERP, POS, HR, CRM),
    extracts the tabular records, and runs the complete AutoML pipeline.
    """
    try:
        base_url = str(request.base_url)
        res = AutoMLService.fetch_and_analyze_external_api(
            api_url=payload.api_url,
            method=payload.method or "GET",
            headers=payload.headers,
            request_body=payload.request_body,
            data_path=payload.data_path,
            dataset_name=payload.dataset_name,
            target_column=payload.target_column,
            date_column=payload.date_column,
            forecast_horizon=payload.forecast_horizon or 14,
            base_url=base_url
        )
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[AutoMLController] Fetch external API error: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses data API: {str(e)}")


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


@router.post("/analyze-and-predict", summary="Auto-Profile, Multi-Model Tournament, Forecast & AI Interpretation")
async def analyze_and_predict(payload: AnalyzeRequest, request: Request):
    """
    Universal AutoML Ingestion Endpoint:
    - Accepts raw tabular JSON array from any external website / API
    - Auto-profiles columns and infers task (Time-Series / Anomaly / Classification)
    - Runs 4-Model Tournament (Fourier, Holt-Winters, Damped Trend, Hybrid Ensemble)
    - Calculates MAPE/RMSE accuracy leaderboard & selects winning model
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


@router.post("/simulate-scenario", summary="Real-Time What-If Scenario Simulator (< 15ms)")
def simulate_scenario(payload: SimulateScenarioRequest):
    """
    Real-Time What-If Scenario Simulation:
    Recalculates forecast trajectories and safety stock curves instantly based on dynamic sliders.
    """
    try:
        res = AutoMLService.simulate_scenario(
            job_id=payload.job_id,
            growth_boost_pct=payload.growth_boost_pct,
            spike_date=payload.spike_date,
            spike_multiplier=payload.spike_multiplier,
            safety_buffer_days=payload.safety_buffer_days
        )
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"[AutoMLController] Simulation error: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal melakukan simulasi: {str(e)}")


@router.post("/ask-ai", summary="Ask AI Interactive Questions About Current Analytics")
def ask_ai(payload: AskAiRequest):
    """
    Interactive Q&A Engine:
    Answers specific analytical or operational questions regarding the current dataset.
    """
    try:
        res = AutoMLService.ask_ai_question(
            job_id=payload.job_id,
            question=payload.question,
            chat_history=payload.chat_history
        )
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"[AutoMLController] Ask AI error: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses pertanyaan AI: {str(e)}")


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
