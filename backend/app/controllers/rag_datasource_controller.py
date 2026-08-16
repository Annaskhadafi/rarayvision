from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database.database import get_db
from ..database.rag_datasource_models import RagExternalDatabase
from ..services.rag_datasource_service import RagDatasourceService

router = APIRouter(prefix="/api/v1/rag/databases", tags=["RAG External Databases"])


class TestConnectionRequest(BaseModel):
    db_url: str = Field(..., description="PostgreSQL connection URL")


class IntrospectRequest(BaseModel):
    db_url: str = Field(..., description="PostgreSQL connection URL")


class CreateDatabaseRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    db_url: str = Field(..., description="PostgreSQL connection string")
    host: Optional[str] = None
    port: Optional[int] = 5432
    database_name: Optional[str] = None
    username: Optional[str] = None
    selected_tables: List[str] = Field(default_factory=list, description="List of tables to ingest into RAG")
    table_configs: Optional[Dict[str, Any]] = None
    auto_sync: Optional[bool] = False
    sync_interval_hours: Optional[int] = 24


class UpdateDatabaseRequest(BaseModel):
    name: Optional[str] = None
    db_url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    username: Optional[str] = None
    selected_tables: Optional[List[str]] = None
    table_configs: Optional[Dict[str, Any]] = None
    auto_sync: Optional[bool] = None
    sync_interval_hours: Optional[int] = None


class SyncDatabaseRequest(BaseModel):
    selected_tables: Optional[List[str]] = None
    max_rows_per_table: Optional[int] = 500


@router.post("/test")
def test_external_database_connection(req: TestConnectionRequest):
    """Tests connectivity to the specified PostgreSQL connection string."""
    result = RagDatasourceService.test_connection(req.db_url)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Gagal terhubung ke database.")
        )
    return result


@router.post("/introspect")
def introspect_external_database_schema(req: IntrospectRequest):
    """Returns list of public tables, row counts, and column schemas for selection."""
    result = RagDatasourceService.introspect_schema(req.db_url)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Gagal membaca schema database.")
        )
    return result


@router.get("")
def list_external_databases(db: Session = Depends(get_db)):
    """Retrieves all registered external database configurations."""
    records = db.query(RagExternalDatabase).order_by(RagExternalDatabase.created_at.desc()).all()
    return {
        "status": "success",
        "total": len(records),
        "databases": [r.to_dict(mask_password=True) for r in records]
    }


@router.post("")
def create_external_database(req: CreateDatabaseRequest, db: Session = Depends(get_db)):
    """Registers a new external database with selected tables."""
    # Test connection first
    test_res = RagDatasourceService.test_connection(req.db_url)
    if not test_res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tidak dapat menyimpan koneksi karena gagal terhubung: {test_res.get('message')}"
        )

    record = RagExternalDatabase(
        name=req.name,
        db_url=req.db_url,
        host=req.host,
        port=req.port,
        database_name=req.database_name,
        username=req.username,
        selected_tables=req.selected_tables or [],
        table_configs=req.table_configs or {},
        auto_sync=req.auto_sync or False,
        sync_interval_hours=req.sync_interval_hours or 24,
        status="active"
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "status": "success",
        "message": f"Koneksi database '{record.name}' berhasil disimpan.",
        "database": record.to_dict(mask_password=True)
    }


@router.put("/{db_id}")
def update_external_database(db_id: str, req: UpdateDatabaseRequest, db: Session = Depends(get_db)):
    """Updates external database connection details or selected tables."""
    record = db.query(RagExternalDatabase).filter(RagExternalDatabase.id == db_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Koneksi database tidak ditemukan.")

    if req.name is not None:
        record.name = req.name
    if req.db_url is not None:
        # If URL changed, test it
        test_res = RagDatasourceService.test_connection(req.db_url)
        if not test_res.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Koneksi baru gagal terhubung: {test_res.get('message')}"
            )
        record.db_url = req.db_url
    if req.host is not None:
        record.host = req.host
    if req.port is not None:
        record.port = req.port
    if req.database_name is not None:
        record.database_name = req.database_name
    if req.username is not None:
        record.username = req.username
    if req.selected_tables is not None:
        record.selected_tables = req.selected_tables
    if req.table_configs is not None:
        record.table_configs = req.table_configs
    if req.auto_sync is not None:
        record.auto_sync = req.auto_sync
    if req.sync_interval_hours is not None:
        record.sync_interval_hours = req.sync_interval_hours

    db.commit()
    db.refresh(record)

    return {
        "status": "success",
        "message": f"Koneksi database '{record.name}' berhasil diperbarui.",
        "database": record.to_dict(mask_password=True)
    }


@router.delete("/{db_id}")
def delete_external_database(db_id: str, db: Session = Depends(get_db)):
    """Deletes an external database configuration."""
    record = db.query(RagExternalDatabase).filter(RagExternalDatabase.id == db_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Koneksi database tidak ditemukan.")

    db.delete(record)
    db.commit()

    return {
        "status": "success",
        "message": f"Koneksi database '{record.name}' berhasil dihapus."
    }


@router.post("/{db_id}/sync")
def sync_external_database(
    db_id: str,
    req: Optional[SyncDatabaseRequest] = None,
    db: Session = Depends(get_db)
):
    """Triggers table extraction, Markdown serialization, and vector ingestion into RAG."""
    override_tables = req.selected_tables if req else None
    max_rows = req.max_rows_per_table if req and req.max_rows_per_table else 500

    result = RagDatasourceService.sync_database_tables(
        db_session=db,
        connection_id=db_id,
        selected_tables_override=override_tables,
        max_rows_per_table=max_rows
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Gagal menyinkronkan tabel ke basis data pengetahuan.")
        )

    return {
        "status": "success",
        "data": result
    }
