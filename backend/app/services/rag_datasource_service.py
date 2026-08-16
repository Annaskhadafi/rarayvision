import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from io import BytesIO
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ..database.rag_datasource_models import RagExternalDatabase
from .rag_service import RagService

logger = logging.getLogger("rarayvision.rag_datasource")

class RagDatasourceService:
    @staticmethod
    def _normalize_db_url(db_url: str) -> str:
        """Ensures PostgreSQL URL uses psycopg2 or compatible driver."""
        url = db_url.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    @classmethod
    def test_connection(cls, db_url: str) -> Dict[str, Any]:
        """Tests connectivity to an external PostgreSQL database with a 5s timeout."""
        start_time = time.perf_counter()
        normalized_url = cls._normalize_db_url(db_url)

        try:
            engine = create_engine(
                normalized_url,
                connect_args={"connect_timeout": 5},
                pool_pre_ping=True
            )
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version();")).fetchone()
                db_version = result[0] if result else "Unknown"

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "success": True,
                "message": "Koneksi berhasil terhubung ke database PostgreSQL eksternal.",
                "db_version": db_version,
                "latency_ms": latency_ms
            }
        except Exception as e:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"[RagDatasource] Test connection failed: {e}")
            return {
                "success": False,
                "message": f"Gagal terhubung ke database: {str(e)}",
                "latency_ms": latency_ms
            }

    @classmethod
    def introspect_schema(cls, db_url: str) -> Dict[str, Any]:
        """
        Introspects the public schema of the external database.
        Returns a list of tables, estimated row counts, and column definitions.
        """
        normalized_url = cls._normalize_db_url(db_url)
        try:
            engine = create_engine(
                normalized_url,
                connect_args={"connect_timeout": 7},
                pool_pre_ping=True
            )
            tables = []

            with engine.connect() as conn:
                # 1. Fetch public table names and estimated row counts
                tables_query = text("""
                    SELECT 
                        t.table_name,
                        COALESCE(s.n_live_tup, 0) AS estimated_rows
                    FROM information_schema.tables t
                    LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
                    WHERE t.table_schema = 'public'
                      AND t.table_type = 'BASE TABLE'
                    ORDER BY t.table_name ASC;
                """)
                tables_res = conn.execute(tables_query).fetchall()

                # 2. Fetch all columns in public schema
                cols_query = text("""
                    SELECT 
                        table_name,
                        column_name,
                        data_type,
                        is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position;
                """)
                cols_res = conn.execute(cols_query).fetchall()

                # Map columns by table
                cols_by_table: Dict[str, List[Dict[str, str]]] = {}
                for row in cols_res:
                    t_name, c_name, d_type, is_null = row[0], row[1], row[2], row[3]
                    if t_name not in cols_by_table:
                        cols_by_table[t_name] = []
                    cols_by_table[t_name].append({
                        "name": c_name,
                        "type": d_type,
                        "nullable": is_null == "YES"
                    })

                # Assemble table list
                for row in tables_res:
                    t_name = row[0]
                    est_rows = row[1]
                    tables.append({
                        "table_name": t_name,
                        "estimated_rows": est_rows,
                        "columns_count": len(cols_by_table.get(t_name, [])),
                        "columns": cols_by_table.get(t_name, [])
                    })

            return {
                "success": True,
                "total_tables": len(tables),
                "tables": tables
            }
        except Exception as e:
            logger.error(f"[RagDatasource] Introspect failed: {e}")
            return {
                "success": False,
                "message": f"Gagal membaca schema database: {str(e)}",
                "tables": []
            }

    @classmethod
    def serialize_table_to_markdown(
        cls,
        engine: Any,
        table_name: str,
        db_name: str,
        max_rows: int = 500
    ) -> str:
        """
        Extracts table rows and serializes them into structured Markdown
        optimized for semantic search and LLM context understanding.
        """
        with engine.connect() as conn:
            # Query columns
            cols_res = conn.execute(text(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = :tname 
                ORDER BY ordinal_position
            """), {"tname": table_name}).fetchall()
            
            columns = [c[0] for c in cols_res]
            col_types = {c[0]: c[1] for c in cols_res}

            # Query rows safely (limit to max_rows)
            # Avoid dangerous SQL injection by verifying table_name matches alphanumeric/underscore
            sanitized_table = "".join(ch for ch in table_name if ch.isalnum() or ch == "_")
            rows_res = conn.execute(text(f"SELECT * FROM public.{sanitized_table} LIMIT :lim"), {"lim": max_rows}).fetchall()

        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        total_rows = len(rows_res)

        md_lines = []
        md_lines.append(f"# Database Table: `{table_name}`")
        md_lines.append(f"**Database**: `{db_name}` | **Total Synced Records**: `{total_rows}` | **Timestamp**: `{now_str}`\n")

        # Schema Table
        md_lines.append(f"## Schema Columns for `{table_name}`")
        md_lines.append("| Column Name | Data Type |")
        md_lines.append("|---|---|")
        for col in columns:
            md_lines.append(f"| `{col}` | {col_types.get(col, 'unknown')} |")
        md_lines.append("")

        if total_rows == 0:
            md_lines.append(f"*Tabel `{table_name}` saat ini kosong (0 data baris).*\n")
            return "\n".join(md_lines)

        # Overview Table (First 20 rows compact)
        display_cols = columns[:8] # Take first 8 important columns for the summary table
        md_lines.append(f"## Data Overview (Top Records)")
        md_lines.append("| " + " | ".join(display_cols) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(display_cols)) + " |")

        for r in rows_res[:25]:
            row_dict = dict(zip(columns, r))
            row_vals = []
            for col in display_cols:
                v = row_dict.get(col)
                v_str = str(v).replace("\n", " ").replace("|", "\\|") if v is not None else "-"
                if len(v_str) > 40:
                    v_str = v_str[:37] + "..."
                row_vals.append(v_str)
            md_lines.append("| " + " | ".join(row_vals) + " |")
        md_lines.append("")

        # Detailed Entity Paragraphs
        md_lines.append(f"## Detailed Entity Records (`{table_name}`)")
        for idx, r in enumerate(rows_res, 1):
            row_dict = dict(zip(columns, r))
            
            # Find an identifier (id, name, title, code)
            identifier_val = row_dict.get("id") or row_dict.get(columns[0]) or idx
            label_val = row_dict.get("name") or row_dict.get("customer_name") or row_dict.get("title") or row_dict.get("code") or ""
            header_suffix = f" - {label_val}" if label_val else ""

            md_lines.append(f"### Record #{idx} [ID: {identifier_val}]{header_suffix}")
            for col in columns:
                val = row_dict.get(col)
                val_str = str(val).strip() if val is not None else "*null*"
                md_lines.append(f"- **{col}**: {val_str}")
            md_lines.append("")

        return "\n".join(md_lines)

    @classmethod
    def sync_database_tables(
        cls,
        db_session: Session,
        connection_id: str,
        selected_tables_override: Optional[List[str]] = None,
        max_rows_per_table: int = 500
    ) -> Dict[str, Any]:
        """
        Connects to external database, serializes selected tables to Markdown,
        and ingests them into the RAG Vector Knowledge Base.
        """
        conn_record = db_session.query(RagExternalDatabase).filter(RagExternalDatabase.id == connection_id).first()
        if not conn_record:
            return {"success": False, "message": f"Koneksi database ID {connection_id} tidak ditemukan."}

        tables_to_sync = selected_tables_override or conn_record.selected_tables or []
        if not tables_to_sync:
            return {"success": False, "message": "Tidak ada tabel yang dipilih untuk disinkronkan."}

        conn_record.status = "syncing"
        db_session.commit()

        start_time = time.perf_counter()
        normalized_url = cls._normalize_db_url(conn_record.db_url)
        synced_results = []
        total_chunks_added = 0

        try:
            engine = create_engine(
                normalized_url,
                connect_args={"connect_timeout": 10},
                pool_pre_ping=True
            )

            db_display_name = conn_record.database_name or conn_record.name

            for table_name in tables_to_sync:
                table_start = time.perf_counter()
                
                # 1. Generate Markdown
                md_content = cls.serialize_table_to_markdown(
                    engine=engine,
                    table_name=table_name,
                    db_name=db_display_name,
                    max_rows=max_rows_per_table
                )

                # 2. Ingest into RAG
                md_bytes = md_content.encode("utf-8")
                filename = f"db_{conn_record.name.lower().replace(' ', '_')}_{table_name}.md"

                ingest_res = RagService.ingest_document(
                    db=db_session,
                    file_bytes=md_bytes,
                    filename=filename,
                    auto_ocr=False,
                    force_ocr=False,
                    format_override="md"
                )

                chunks_count = ingest_res.get("total_chunks", 0)
                total_chunks_added += chunks_count
                t_elapsed = round((time.perf_counter() - table_start) * 1000, 2)

                synced_results.append({
                    "table_name": table_name,
                    "document_id": ingest_res.get("document_id"),
                    "filename": filename,
                    "s3_url": ingest_res.get("s3_url"),
                    "total_chunks": chunks_count,
                    "elapsed_ms": t_elapsed
                })

            # Update DB Record
            conn_record.status = "active"
            conn_record.last_synced_at = datetime.utcnow()
            conn_record.last_sync_status = "success"
            conn_record.last_error_message = None
            conn_record.total_docs_synced = len(synced_results)
            conn_record.total_chunks_synced = total_chunks_added
            db_session.commit()

            total_elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return {
                "success": True,
                "message": f"Berhasil menyinkronkan {len(synced_results)} tabel ({total_chunks_added} vektor chunks) ke RAG Knowledge Base.",
                "total_tables_synced": len(synced_results),
                "total_chunks_added": total_chunks_added,
                "elapsed_ms": total_elapsed_ms,
                "details": synced_results
            }

        except Exception as e:
            logger.error(f"[RagDatasource] Sync failed: {e}")
            conn_record.status = "error"
            conn_record.last_sync_status = "error"
            conn_record.last_error_message = str(e)
            db_session.commit()
            return {
                "success": False,
                "message": f"Gagal menyinkronkan data database: {str(e)}",
                "details": synced_results
            }
