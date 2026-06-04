import os


class Config:
    LITELLM_BASE_URL: str = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000")
    LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "sk-localdummy")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "chat")
    OUTPUT_DIR: str = os.environ.get("OUTPUT_DIR", "output/")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    MAX_COLUMNS: int = int(os.environ.get("MAX_COLUMNS", "50"))


config = Config()
