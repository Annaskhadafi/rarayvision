import os
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")), ".env"))

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    DB_TYPE = os.getenv("DB_TYPE", "postgresql").lower()
    DB_USER = os.getenv("DB_USER", "raray")
    DB_PASS = os.getenv("DB_PASS", "yourpassword")
    DB_HOST = os.getenv("DB_HOST", "db")
    DB_PORT = os.getenv("DB_PORT", "5432" if DB_TYPE == "postgresql" else "3306")
    DB_NAME = os.getenv("DB_NAME", "rarayvision")

    if DB_TYPE == "postgresql":
        DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    elif DB_TYPE == "mysql":
        DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    else:
        DATABASE_URL = f"sqlite:///./rarayvision.db"

# Environment mode: "development" (default) or "production"
ENV = os.getenv("ENV", "development").lower()

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "af8ab971bf9210d90d5b615f4e5359594707750d582e8d824a973e329726ee42")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days


# Base paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Model paths (inside backend/ml_models/)
ANTI_SPOOF_MODEL_PATH = os.path.join(BASE_DIR, "ml_models", "MiniFASNetV2.onnx")
EMOTION_MODEL_PATH = os.path.join(BASE_DIR, "ml_models", "emotion-ferplus-8.onnx")
