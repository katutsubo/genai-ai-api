import chardet
import pandas as pd

from agent.config import config
from agent.logging_config import get_logger
from agent.models import ParsedData

logger = get_logger(__name__)


class CSVParser:
    def parse(self, file_path: str) -> ParsedData:
        with open(file_path, "rb") as f:
            raw = f.read()

        if not raw:
            raise ValueError(f"empty file: {file_path}")

        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"

        try:
            df = pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding="utf-8", errors="replace")
            encoding = "utf-8"
        except pd.errors.ParserError as e:
            raise ValueError(f"CSV parse error: {e}") from e
        except pd.errors.EmptyDataError as e:
            raise ValueError(f"empty file: {e}") from e

        if len(df.columns) > config.MAX_COLUMNS:
            logger.warning(
                f"Column count {len(df.columns)} exceeds MAX_COLUMNS={config.MAX_COLUMNS}, truncating"
            )
            df = df.iloc[:, : config.MAX_COLUMNS]

        return ParsedData(
            file_path=file_path,
            file_type="csv",
            df=df,
            encoding=encoding,
        )
