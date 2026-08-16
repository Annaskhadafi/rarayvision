import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Boolean
from .database import Base

class RagExternalDatabase(Base):
    """
    Stores connection configurations for external PostgreSQL databases
    and the user-selected tables to ingest into the RAG Knowledge Base.
    """
    __tablename__ = "rag_external_databases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    db_url = Column(Text, nullable=False) # e.g. postgresql://user:pass@host:port/dbname
    host = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True, default=5432)
    database_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    
    # List of table names selected by the user, e.g. ["customers", "invoices", "orders"]
    selected_tables = Column(JSON, default=list)

    # Optional table metadata (column configurations or custom row limit)
    table_configs = Column(JSON, default=dict)

    # Status & stats
    status = Column(String(50), default="active") # active, syncing, error, idle
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String(50), nullable=True)
    last_error_message = Column(Text, nullable=True)
    total_docs_synced = Column(Integer, default=0)
    total_chunks_synced = Column(Integer, default=0)

    # Sync schedule
    auto_sync = Column(Boolean, default=False)
    sync_interval_hours = Column(Integer, default=24)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, mask_password: bool = True) -> dict:
        url_display = self.db_url
        if mask_password and url_display and "@" in url_display:
            try:
                # Mask password in URL for UI safety: postgresql://user:****@host:port/db
                prefix, rest = url_display.split("://", 1)
                auth, host_db = rest.split("@", 1)
                user = auth.split(":", 1)[0]
                url_display = f"{prefix}://{user}:••••••••@{host_db}"
            except Exception:
                url_display = "postgresql://••••:••••@host/db"

        return {
            "id": self.id,
            "name": self.name,
            "db_url": url_display,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "username": self.username,
            "selected_tables": self.selected_tables or [],
            "table_configs": self.table_configs or {},
            "status": self.status,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_sync_status": self.last_sync_status,
            "last_error_message": self.last_error_message,
            "total_docs_synced": self.total_docs_synced,
            "total_chunks_synced": self.total_chunks_synced,
            "auto_sync": self.auto_sync,
            "sync_interval_hours": self.sync_interval_hours,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
