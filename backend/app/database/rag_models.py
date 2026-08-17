from sqlalchemy import Column, String, Integer, Float, Boolean, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base
try:
    from .models import User
except ImportError:
    pass


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
    embedding = Column(JSON, nullable=True)  # 384-dimensional vector float array
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("RagDocument", back_populates="chunks")


class RagChatSession(Base):
    """
    Persistent Multi-Turn Chat Conversation Session.
    Enables persistent session memory across device refreshes and system restarts.
    """
    __tablename__ = "rag_chat_sessions"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), default="Percakapan Hero Assistant")
    document_id = Column(String(64), ForeignKey("rag_documents.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    meta_info = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    messages = relationship("RagChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="RagChatMessage.created_at")


class RagChatMessage(Base):
    """
    Persistent Individual Turn Message in a RAG Chat Session.
    Stores user queries, AI responses, citation sources, and user feedback/corrections.
    """
    __tablename__ = "rag_chat_messages"

    id = Column(String(64), primary_key=True, index=True)
    session_id = Column(String(64), ForeignKey("rag_chat_sessions.id", ondelete="CASCADE"), index=True)
    role = Column(String(32), nullable=False)  # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    sources = Column(JSON, default=[])
    retrieved_chunks_count = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    rating = Column(Integer, nullable=True)  # 1 = Thumbs Up, -1 = Thumbs Down
    feedback_notes = Column(Text, nullable=True)
    correction_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("RagChatSession", back_populates="messages")


class RagMemoryFact(Base):
    """
    Long-Term Dynamic Memory & Self-Growth Knowledge Base.
    Stores facts learned from user corrections, preferences, and verified feedback.
    Vector embeddings enable semantic fact recall in future RAG queries.
    """
    __tablename__ = "rag_memory_facts"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    fact_type = Column(String(64), default="learned_knowledge")  # "learned_knowledge", "user_correction", "rule", "preference"
    subject = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    confidence_score = Column(Float, default=1.0)
    source_session_id = Column(String(64), nullable=True)
    source_message_id = Column(String(64), nullable=True)
    embedding = Column(JSON, nullable=True)  # 384-dimensional vector float array
    is_active = Column(Boolean, default=True, index=True)
    learned_from = Column(String(128), default="user_feedback")  # "user_feedback", "direct_input", "auto_extractor"
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
