import os

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)

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
DATABRICKS_WORKSPACES = os.getenv("DATABRICKS_WORKSPACES")
DATABRICKS_STATEMENTS_URL = os.getenv("DATABRICKS_STATEMENTS")
DATABRICKS_TOKEN_URL = os.getenv("DATABRICKS_TOKEN_URL")
DATABRICKS_CLIENT_ID = os.getenv("DATABRICKS_CLIENT_ID")
DATABRICKS_CLIENT_SECRET = os.getenv("DATABRICKS_CLIENT_SECRET")


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


# Qdrant
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_TIMEOUT_S = int(os.getenv("QDRANT_TIMEOUT_S", "30"))
QDRANT_DOMAIN_COLLECTION = os.getenv("QDRANT_DOMAIN_COLLECTION", "domain_catalog_v1")
QDRANT_TABLE_COLLECTION = os.getenv("QDRANT_TABLE_COLLECTION", "table_catalog")
QDRANT_COLUMN_COLLECTION = os.getenv("QDRANT_COLUMN_COLLECTION", "column_catalog")
QDRANT_COLUMN_COLLECTION_V2 = os.getenv("QDRANT_COLUMN_COLLECTION_V2", "column_catalog_v2")
QDRANT_SEMANTIC_CONCEPT_COLLECTION = os.getenv("QDRANT_SEMANTIC_CONCEPT_COLLECTION", "semantic_concepts_v1")

# Embedding + vertical defaults
EMBEDDING_MODEL_NAME = (
    os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2").strip()
    or "sentence-transformers/all-MiniLM-L6-v2"
)
QF_VERTICAL_DEFAULT = (
    os.getenv("QF_VERTICAL_DEFAULT", os.getenv("SEMANTIC_VERTICAL_DEFAULT", "generic")).strip().lower()
    or "generic"
)
METADATA_SOURCE_MODE = (
    os.getenv("METADATA_SOURCE_MODE", "workspace").strip().lower()
    or "workspace"
)

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
SEMANTIC_PLAN_LLM_MAX_TOKENS = int(os.getenv("SEMANTIC_PLAN_LLM_MAX_TOKENS", "1200"))
QF_WORKSPACE_LLM_RUNTIME_ENABLED = os.getenv("QF_WORKSPACE_LLM_RUNTIME_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
SEMANTIC_CONCEPT_SEED_ON_STARTUP = os.getenv("SEMANTIC_CONCEPT_SEED_ON_STARTUP", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLANNER_LLM_ENABLED = os.getenv("QF_PLANNER_LLM_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED = os.getenv("QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED = os.getenv("QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS", 220)
QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED = os.getenv("QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_FAST_MODE_DEFAULT = os.getenv("QF_PLAN_DOMAIN_FAST_MODE_DEFAULT", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
PLANNER_UNIFIED_LLM = os.getenv("PLANNER_UNIFIED_LLM", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED = os.getenv("QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS", 700)
QF_PLAN_DOMAIN_COMPACT_RETRY_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_COMPACT_RETRY_MAX_TOKENS", 420)
QF_PLAN_DOMAIN_COMPACT_FALLBACK_MODEL = (os.getenv("QF_PLAN_DOMAIN_COMPACT_FALLBACK_MODEL", "") or "").strip()
QF_PLAN_DOMAIN_COMPACT_REASONING_EFFORT = (os.getenv("QF_PLAN_DOMAIN_COMPACT_REASONING_EFFORT", "") or "").strip().lower()
QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES = _env_int("QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES", 5)
QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES = _env_int("QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES", 8)
QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES = _env_int("QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES", 8)
QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES = _env_int("QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES", 3)
QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE = _env_float("QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE", 0.01)
QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS", 300)
QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS", 220)
QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS = _env_int("QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS", 40)
QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS = _env_int("QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS", 45)
QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT = os.getenv("QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS = _env_int("QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS", 380)
QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS = _env_int("QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS", 3)
QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED = os.getenv("QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE = (
    os.getenv("QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", "logs/plan_domain_pipeline_timing.log").strip()
    or "logs/plan_domain_pipeline_timing.log"
)
QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED = os.getenv("QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE = (
    os.getenv("QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE", "logs/plan_domain_pipeline_trace.jsonl").strip()
    or "logs/plan_domain_pipeline_trace.jsonl"
)
QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS = _env_int("QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS", 12000)
QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS = _env_int("QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS", 100)
QF_SCHOOL_YEAR_START_MONTH = _env_int("QF_SCHOOL_YEAR_START_MONTH", 8)
QF_SCHOOL_YEAR_END_MONTH = _env_int("QF_SCHOOL_YEAR_END_MONTH", 7)
QF_SEMESTER_SPRING_LABEL = (os.getenv("QF_SEMESTER_SPRING_LABEL", "Spring") or "Spring").strip() or "Spring"
QF_SEMESTER_FALL_LABEL = (os.getenv("QF_SEMESTER_FALL_LABEL", "Fall") or "Fall").strip() or "Fall"
QF_SEMESTER_YEAR_ROUND_LABEL = (
    os.getenv("QF_SEMESTER_YEAR_ROUND_LABEL", "Year Round") or "Year Round"
).strip() or "Year Round"
QF_SEMESTER_SPRING_START_MONTH = _env_int("QF_SEMESTER_SPRING_START_MONTH", 1)
QF_SEMESTER_SPRING_END_MONTH = _env_int("QF_SEMESTER_SPRING_END_MONTH", 5)
QF_SEMESTER_FALL_START_MONTH = _env_int("QF_SEMESTER_FALL_START_MONTH", 8)
QF_SEMESTER_FALL_END_MONTH = _env_int("QF_SEMESTER_FALL_END_MONTH", 12)
QF_SEMESTER_YEAR_ROUND_START_MONTH = _env_int("QF_SEMESTER_YEAR_ROUND_START_MONTH", 6)
QF_SEMESTER_YEAR_ROUND_END_MONTH = _env_int("QF_SEMESTER_YEAR_ROUND_END_MONTH", 7)
QF_MINIMAL_CHAT_ENABLED = os.getenv("QF_MINIMAL_CHAT_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_ENABLED = os.getenv("QF_FORGE_INSIGHTS_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_AUTO_PLAN_ENABLED = os.getenv("QF_FORGE_INSIGHTS_AUTO_PLAN_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_ROUTE_CONFIDENCE_THRESHOLD = _env_float("QF_FORGE_INSIGHTS_ROUTE_CONFIDENCE_THRESHOLD", 0.65)
QF_FORGE_INSIGHTS_ROUTE_LLM_MAX_TOKENS = _env_int("QF_FORGE_INSIGHTS_ROUTE_LLM_MAX_TOKENS", 120)
QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_ENABLED = os.getenv(
    "QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_ENABLED",
    "1",
).strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_LIMIT = _env_int("QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_LIMIT", 8)
QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_SCAN_LIMIT = _env_int("QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_SCAN_LIMIT", 120)
QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_CACHE_SECONDS = _env_int("QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_CACHE_SECONDS", 300)
QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_MAX_PROMPT_CHARS = _env_int("QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_MAX_PROMPT_CHARS", 220)
QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_ENABLED = os.getenv(
    "QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_ENABLED",
    "1",
).strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_LIMIT = _env_int("QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_LIMIT", 1)
QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_SCORE_THRESHOLD = _env_float(
    "QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_SCORE_THRESHOLD",
    0.2,
)
QF_DOMAIN_PROFILE_LLM_MAX_TOKENS = _env_int("QF_DOMAIN_PROFILE_LLM_MAX_TOKENS", 3200)
QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS = int(
    os.getenv("QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS", "43200")
)
QF_FORGE_INSIGHTS_CONVERSATION_TTL_SECONDS = int(
    os.getenv("QF_FORGE_INSIGHTS_CONVERSATION_TTL_SECONDS", str(QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS))
)
QF_INGESTION_STALE_GUARD_ENABLED = os.getenv("QF_INGESTION_STALE_GUARD_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_INGESTION_STALE_SECONDS = _env_int("QF_INGESTION_STALE_SECONDS", 900)
QF_FORGE_INSIGHTS_MAX_HISTORY_MESSAGES = _env_int("QF_FORGE_INSIGHTS_MAX_HISTORY_MESSAGES", 80)
QF_FORGE_INSIGHTS_MAX_CONTEXT_CHARS = _env_int("QF_FORGE_INSIGHTS_MAX_CONTEXT_CHARS", 24000)
QF_FORGE_INSIGHTS_SUMMARY_ENABLED = os.getenv("QF_FORGE_INSIGHTS_SUMMARY_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
QF_FORGE_INSIGHTS_SUMMARY_TRIGGER_MESSAGES = _env_int("QF_FORGE_INSIGHTS_SUMMARY_TRIGGER_MESSAGES", 24)
QF_FORGE_INSIGHTS_LIST_LIMIT = _env_int("QF_FORGE_INSIGHTS_LIST_LIMIT", 50)
QF_PLAN_DOMAIN_CONVERSATION_TTL_SECONDS = int(
    os.getenv("QF_PLAN_DOMAIN_CONVERSATION_TTL_SECONDS", "43200")
)
QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES = _env_int("QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES", 2_000_000)

# Tier2 NLP (spaCy transformer)
NLP_TIER2_ENABLED = os.getenv("NLP_TIER2_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
NLP_TIER2_MODEL_PATH = os.getenv("NLP_TIER2_MODEL_PATH", "").strip()
NLP_TIER2_MODEL_NAME = os.getenv("NLP_TIER2_MODEL_NAME", "roberta-base").strip() or "roberta-base"

# spaCy planner extraction
SPACY_MODEL_PATH = (
    os.getenv("SPACY_MODEL_PATH", "").strip()
    or NLP_TIER2_MODEL_PATH
    or "models/tier2/model-best"
)
GAZETTEER_ENABLED = os.getenv("GAZETTEER_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)
GAZETTEER_CSV_PATH = os.getenv("GAZETTEER_CSV_PATH", "data/school_districts.csv").strip() or "data/school_districts.csv"

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
DESTINATION_ENCRYPTION_KEY = os.getenv("DESTINATION_ENCRYPTION_KEY", "").strip() or None
