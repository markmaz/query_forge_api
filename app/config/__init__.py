import os

from dotenv import load_dotenv

load_dotenv()

DB_HOST =  os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT")
DB_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXP_DELTA_HOURS = 2
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "120"))
JWT_VERIFY_IAT = os.getenv("JWT_VERIFY_IAT", "").strip().lower() in ("1", "true", "yes", "y", "on")
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900"))
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "1209600"))
OTP_VALID_WINDOW = int(os.getenv("OTP_VALID_WINDOW", "2"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "y", "on")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", "/api/v1/auth")

DATABRICKS_URL = os.getenv("DATABRICKS_URL")
DATABRICKS_BASE_ACCOUNT_URL = os.getenv("DATABRICKS_BASE_ACCOUNT_URL")
DATABRICKS_WORKSPACE_USERS_URL = os.getenv("DATABRICKS_WORKSPACE_USERS_URL")
DATABRICKS_WAREHOUSE_URL = os.getenv("DATABRICKS_WAREHOUSE_URL")
DATABRICKS_WORKSPACES = os.getenv("DATABRICKS_WORKSPACES")
DATABRICKS_STATEMENTS_URL = os.getenv("DATABRICKS_STATEMENTS")
DATABRICKS_TOKEN_URL = os.getenv("DATABRICKS_TOKEN_URL")
DATABRICKS_CLIENT_ID = os.getenv("DATABRICKS_CLIENT_ID")
DATABRICKS_CLIENT_SECRET = os.getenv("DATABRICKS_CLIENT_SECRET")
DEFAULT_SQL_WAREHOUSE = os.getenv("DEFAULT_SQL_WAREHOUSE")



SIGMA_BASE_URL = os.getenv("SIGMA_BASE_URL", "")
SIGMA_WORKSPACE= os.getenv("SIGMA_WORKSPACE", "")
SIGMA_CLIENT_ID = os.getenv("SIGNMA_CLIENT_ID", "")
SIGMA_SECRET = os.getenv("SIGMA_CLIENT_SECRET", "")
SIGMA_EMBED_CLIENT_ID = os.getenv("SIGMA_EMBED_CLIENT_ID", "")
SIGMA_EMBED_SECRET = os.getenv("SIGMA_EMBED_SECRET", "")
SIGMA_TAGS_RAW = os.getenv("SIGMA_TAGS", "")
SIGMA_TAGS = [tag.strip() for tag in SIGMA_TAGS_RAW.split(",") if tag]
SIGMA_TAG_URL = os.getenv("SIGMA_TAG_URL", "")

SIGMA_JWT_CLIENT_ID=os.getenv("SIGMA_JWT_CLIENT_ID")
SIGMA_JWT_CLIENT_SECRET=os.getenv("SIGMA_JWT_CLIENT_SECRET")
SIGMA_JWT_BASE_URL=os.getenv("SIGMA_ORGANIZATION_SLUG")


POOL_SIZE=10
MAX_OVERFLOW=20
POOL_TIMEOUT=30
POOL_RECYCLE=1800
VALKEY_ADDRESS=os.getenv("VALKEY_ADDRESS")
VALKEY_PORT=os.getenv("VALKEY_PORT")
USE_CLUSTER=os.getenv("USE_CLUSTER")
IS_STAND_ALONE=os.getenv("IS_STAND_ALONE")
VALKEY_CONFIG=f"redis://{VALKEY_ADDRESS}:{VALKEY_PORT}/0"
LOG_QUEUE=os.getenv("LOG_QUEUE")

CURRENT_ENVIRONMENT=os.getenv("CURRENT_ENVIRONMENT")
PASSWORD_CHECK_URL=os.getenv("PASSWORD_CHECK_URL")
MIN_PASSWORD_LENGTH=os.getenv("MIN_PASSWORD_LENGTH")

SMTP_USERNAME=os.getenv("SMTP_USERNAME")
SMTP_PASSWORD=os.getenv("SMTP_PASSWORD")
SMTP_SERVER=os.getenv("SMTP_SERVER")
SMTP_PORT=os.getenv("SMPT_PORT")
DEFAULT_MAIL_SENDER=os.getenv("DEFAULT_MAIL_SENDER")
INVITE_URL=os.getenv("INVITE_URL")
PASSWORD_RESET_URL=os.getenv("PASSWORD_RESET_URL")

SALES_INQUIRY_EMAIL = os.getenv("SALES_INQUIRY_EMAIL") or os.getenv("sales_inquiry_email")
ERROR_VALIDATION_URL = (
    os.getenv("ERROR_VALIDATION_URL")
    or os.getenv("error_validation_url")
    or "/request-walkthrough?error=validation"
)
ERROR_SERVER_URL = (
    os.getenv("ERROR_SERVER_URL")
    or os.getenv("error_server_url")
    or "/request-walkthrough?error=server"
)
THANK_YOU_REDIRECT = (
    os.getenv("THANK_YOU_REDIRECT")
    or os.getenv("thank_you_redirect")
    or "/thank-you"
)
# OPEN_AI_KEY=os.getenv("OPEN_AI_KEY")
# CENTRAL_TAVILY_API_KEY=os.getenv("CENTRAL_TAVILY_API_KEY")
# AI_MODEL_NAME=os.getenv("AI_MODEL_NAME")

# vLLM (OpenAI-compatible local server)
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "qwen25-7b")
VLLM_TIMEOUT = int(os.getenv("VLLM_TIMEOUT", "60"))

# LLM EC2 environment control
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN", "").strip() or None
LLM_INSTANCE_ID = os.getenv("LLM_INSTANCE_ID", "").strip()
LLM_STATUS_CACHE_SECONDS = int(os.getenv("LLM_STATUS_CACHE_SECONDS", "5"))

# Databricks model snapshot (Delta)
DBX_MODEL_SNAPSHOT_CATALOG = os.getenv("DBX_MODEL_SNAPSHOT_CATALOG", "analytics")
DBX_MODEL_SNAPSHOT_SCHEMA = os.getenv("DBX_MODEL_SNAPSHOT_SCHEMA", "workboard")
DBX_MODEL_COLUMNS_SNAPSHOT_TABLE = os.getenv("DBX_MODEL_COLUMNS_SNAPSHOT_TABLE", "model_columns_snapshot")
DBX_MODEL_TABLES_SNAPSHOT_TABLE = os.getenv("DBX_MODEL_TABLES_SNAPSHOT_TABLE", "model_tables_snapshot")

# Qdrant
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_TIMEOUT_S = int(os.getenv("QDRANT_TIMEOUT_S", "30"))
QDRANT_DOMAIN_COLLECTION = os.getenv("QDRANT_DOMAIN_COLLECTION", "domain_catalog")
QDRANT_TABLE_COLLECTION = os.getenv("QDRANT_TABLE_COLLECTION", "table_catalog")
QDRANT_COLUMN_COLLECTION = os.getenv("QDRANT_COLUMN_COLLECTION", "column_catalog")
QDRANT_COLUMN_COLLECTION_V2 = os.getenv("QDRANT_COLUMN_COLLECTION_V2", "column_catalog_v2")
QDRANT_SEMANTIC_CONCEPT_COLLECTION = os.getenv("QDRANT_SEMANTIC_CONCEPT_COLLECTION", "semantic_concepts_v1")

# Semantic suggestion backfill
SEMANTIC_LLM_ENDPOINT = os.getenv("SEMANTIC_LLM_ENDPOINT", "http://localhost:8000/v1/chat/completions")
SEMANTIC_LLM_MODEL = os.getenv("SEMANTIC_LLM_MODEL", "qwen25-7b")
SEMANTIC_LLM_TIMEOUT_SECONDS = int(os.getenv("SEMANTIC_LLM_TIMEOUT_SECONDS", "60"))
SEMANTIC_LLM_MAX_CONCURRENCY = int(os.getenv("SEMANTIC_LLM_MAX_CONCURRENCY", "2"))
SEMANTIC_LLM_BATCH_SIZE = int(os.getenv("SEMANTIC_LLM_BATCH_SIZE", "20"))
SEMANTIC_AUTO_APPROVE_THRESHOLD = float(os.getenv("SEMANTIC_AUTO_APPROVE_THRESHOLD", "0.85"))
SEMANTIC_AUTO_APPROVE_MAX_ERRORS = int(os.getenv("SEMANTIC_AUTO_APPROVE_MAX_ERRORS", "0"))
SEMANTIC_SAMPLE_VALUES_LIMIT = int(os.getenv("SEMANTIC_SAMPLE_VALUES_LIMIT", "20"))
SEMANTIC_STATS_ENABLED = os.getenv("SEMANTIC_STATS_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y", "on")
SEMANTIC_VERTICAL_DEFAULT = os.getenv("SEMANTIC_VERTICAL_DEFAULT", "generic").strip().lower() or "generic"
SEMANTIC_PLAN_LLM_MODEL = (
    os.getenv("SEMANTIC_PLAN_LLM_MODEL", VLLM_MODEL).strip() or VLLM_MODEL
)
SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS = int(os.getenv("SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS", "60"))
SEMANTIC_CONCEPT_SEED_ON_STARTUP = os.getenv("SEMANTIC_CONCEPT_SEED_ON_STARTUP", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
