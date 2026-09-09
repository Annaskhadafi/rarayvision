from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.deps import get_current_user
from ..services.forecasting_service import forecast, inspect_schema

router = APIRouter(prefix="/api/v1/forecasting", tags=["Time Series Forecasting"])


class DatabaseRequest(BaseModel):
    db_url: str = Field(..., min_length=1)


class ForecastRequest(DatabaseRequest):
    table_name: str = Field(..., min_length=1)
    time_column: str = Field(..., min_length=1)
    value_column: str = Field(..., min_length=1)
    horizon: int = Field(default=12, ge=1, le=256)
    context_length: int = Field(default=128, ge=8, le=2048)


@router.post("/schema")
def get_forecasting_schema(request: DatabaseRequest, _current_user=Depends(get_current_user)):
    try:
        return {"status": "success", **inspect_schema(request.db_url)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/forecast")
def run_forecast(request: ForecastRequest, _current_user=Depends(get_current_user)):
    try:
        return {"status": "success", "data": forecast(**request.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
