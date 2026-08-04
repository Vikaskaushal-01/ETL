from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DB: str = "agentic_ai_etl"
    MYSQL_USER: str = "etl_user"
    MYSQL_PASSWORD: str = "etl_password"
    
    STAGING_MYSQL_DB: str = "agentic_ai_etl_staging"
    STAGING_MYSQL_USER: str = "etl_user"
    STAGING_MYSQL_PASSWORD: str = "etl_password"
    
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    GEMINI_API_KEY: Optional[str] = None
    OLLAMA_HOST: str = "http://localhost:11434"
    LLM_PROVIDER: str = "gemini"
    
    ENV: str = "development"
    DATA_DIR: str = "data"
    REPORTS_DIR: str = "reports"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

def get_settings():
    return settings
