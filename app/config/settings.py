"""
Application configuration — loaded from environment variables via pydantic-settings.
All secrets must be supplied through .env or the container environment.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "SafeHer API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"   # development | staging | production

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4                  # Uvicorn/Gunicorn worker count
    RELOAD: bool = False

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., description="JWT signing secret — MUST be overridden")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    BCRYPT_ROUNDS: int = 12

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "https://safeher.app"]
    ALLOWED_METHODS: list[str] = ["*"]
    ALLOWED_HEADERS: list[str] = ["*"]

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "safeher"
    MONGODB_MAX_POOL_SIZE: int = 100   # handles 5000 users across workers
    MONGODB_MIN_POOL_SIZE: int = 10
    MONGODB_MAX_IDLE_TIME_MS: int = 30_000

    # ── Redis (rate limiting + pub/sub + sessions) ────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 200

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 100     # per minute per IP
    RATE_LIMIT_SOS_REQUESTS: int = 10  # stricter for SOS to prevent abuse
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ── Twilio (SMS + voice) ──────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    # ── SendGrid (email) ──────────────────────────────────────────────────────
    SENDGRID_API_KEY: str = ""
    FROM_EMAIL: str = "no-reply@safeher.app"
    FROM_NAME: str = "SafeHer Safety Team"

    # ── Firebase (push notifications) ────────────────────────────────────────
    FIREBASE_CREDENTIALS_PATH: str = "firebase-credentials.json"
    FIREBASE_ENABLED: bool = False

    # ── Google Maps ───────────────────────────────────────────────────────────
    GOOGLE_MAPS_API_KEY: str = ""

    # ── OpenAI (Aria AI chatbot) ──────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 500
    OPENAI_TEMPERATURE: float = 0.7

    # ── AWS S3 (voice/media uploads) ─────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    AWS_S3_BUCKET: str = "safeher-uploads"

    # ── WebSocket ─────────────────────────────────────────────────────────────
    WS_HEARTBEAT_INTERVAL: int = 30   # seconds
    WS_MAX_CONNECTIONS_PER_USER: int = 3

    # ── ML Models ─────────────────────────────────────────────────────────────
    ML_MODELS_DIR: str = "app/ml/models"
    SCREAM_DETECTION_THRESHOLD: float = 0.75
    DISTRESS_DETECTION_THRESHOLD: float = 0.70
    ML_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — import this everywhere instead of Settings()."""
    return Settings()


settings = get_settings()
