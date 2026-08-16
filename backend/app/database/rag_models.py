from sqlalchemy import Column, String, Integer, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

try:
    from app.database.database import Base
except ImportError:
    from backend.app.database.database import Base


class RagDocument(Base):
    """
    Parent document uploaded and ingested into the RAG knowledge base.
    """
    __tablename__ = "rag_documents"

    id = Column(String(64), primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    format = Column(String(32), nullable=False)
    s3_url = Column(String(1024), nullable=True)
    local_url = Column(String(1024), nullable=True)
    char_count = Column(Integer, default=0)
    word_count = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    engine_used = Column(String(64), default="anydoc")
    embedding_model = Column(String(128), default="BAAI/bge-small-en-v1.5")
    extra_meta = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    chunks = relationship("RagDocumentChunk", back_populates="document", cascade="all, delete-orphan")


class RagDocumentChunk(Base):
    """
    Individual semantic chunk of Markdown text indexed with vector embeddings.
    Embeddings are stored as vector float arrays in JSON/Postgres JSON format for universal compatibility.
    """
    __tablename__ = "rag_document_chunks"

    id = Column(String(64), primary_key=True, index=True)
    document_id = Column(String(64), ForeignKey("rag_documents.id", ondelete="CASCADE"), index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    heading = Column(String(255), nullable=True)
    token_count = Column(Integer, default=0)
    metadata_info = Column(JSON, default={})
    embedding = Column(JSON, nullable=True) # 384-dimensional vector float array
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("RagDocument", back_populates="chunks")
