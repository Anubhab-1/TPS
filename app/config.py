from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    REDIS_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
