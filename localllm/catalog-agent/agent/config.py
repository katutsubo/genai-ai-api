import os


class Config:
    LITELLM_BASE_URL: str = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000")
    LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "sk-localdummy")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "chat")
    OUTPUT_DIR: str = os.environ.get("OUTPUT_DIR", "output/")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    MAX_COLUMNS: int = int(os.environ.get("MAX_COLUMNS", "50"))
    # 画面(ブラウザ)からダウンロードリンクを開くための公開ベースURL。
    # catalog-agent は 8002 をホストへ公開しているため既定は http://localhost:8002。
    PUBLIC_BASE_URL: str = os.environ.get("CATALOG_PUBLIC_BASE_URL", "http://localhost:8002")


config = Config()
