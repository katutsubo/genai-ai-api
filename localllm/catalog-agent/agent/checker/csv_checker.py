import os
import re

import pandas as pd
import yaml

from agent.checker.check_result import make_result
from agent.logging_config import get_logger
from agent.models import CheckResult, ParsedData

logger = get_logger(__name__)

_DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "../../rules/rules_csv.yaml")


class CSVChecker:
    def __init__(self, rules_path: str = _DEFAULT_RULES_PATH):
        with open(rules_path) as f:
            self._rules = yaml.safe_load(f)["rules"]

    def check(self, parsed: ParsedData) -> list[CheckResult]:
        results = []
        df = parsed.df
        for rule in self._rules:
            rid = rule["id"]
            name = rule["name"]
            sev = rule["severity"]
            params = rule.get("params", {})

            if rid == "STR-001":
                required = params.get("columns", [])
                missing = [c for c in required if c not in df.columns]
                if missing:
                    for col in missing:
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                False,
                                f"必須カラム '{col}' が存在しません",
                                f"column:{col}",
                            )
                        )
                else:
                    results.append(
                        make_result(rid, name, sev, True, "必須カラムすべて存在します", "table")
                    )

            elif rid == "STR-002":
                pattern = params.get("pattern", r"^[a-z][a-z0-9_]{0,63}$")
                violations = [col for col in df.columns if not re.match(pattern, col)]
                if violations:
                    for col in violations:
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                False,
                                f"カラム名が規約に違反: '{col}'",
                                f"column:{col}",
                            )
                        )
                else:
                    results.append(
                        make_result(
                            rid, name, sev, True, "全カラム名が命名規約に準拠しています", "table"
                        )
                    )

            elif rid == "TYP-001":
                suffixes = params.get("suffix", ["_date", "_at", "_on"])
                for col in df.columns:
                    if any(col.endswith(s) for s in suffixes):
                        valid = True
                        for val in df[col].dropna().astype(str):
                            if not re.match(r"^\d{4}-\d{2}-\d{2}$", val.strip()):
                                valid = False
                                results.append(
                                    make_result(
                                        rid,
                                        name,
                                        sev,
                                        False,
                                        f"日付カラム '{col}' に YYYY-MM-DD 以外の値: '{val}'",
                                        f"column:{col}",
                                    )
                                )
                                break
                        if valid:
                            results.append(
                                make_result(
                                    rid,
                                    name,
                                    sev,
                                    True,
                                    f"日付カラム '{col}' フォーマット正常",
                                    f"column:{col}",
                                )
                            )

            elif rid == "TYP-002":
                suffixes = params.get("suffix", ["_id", "_count", "_amount"])
                for col in df.columns:
                    if any(col.endswith(s) for s in suffixes):
                        if not pd.api.types.is_numeric_dtype(df[col]):
                            results.append(
                                make_result(
                                    rid,
                                    name,
                                    sev,
                                    False,
                                    f"数値カラム '{col}' が数値型でありません",
                                    f"column:{col}",
                                )
                            )
                        else:
                            results.append(
                                make_result(
                                    rid,
                                    name,
                                    sev,
                                    True,
                                    f"数値カラム '{col}' 型正常",
                                    f"column:{col}",
                                )
                            )

            elif rid == "INT-001":
                required = params.get("columns", [])
                for col in required:
                    if col in df.columns and df[col].isnull().any():
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                False,
                                f"NOT NULL カラム '{col}' に NULL 値が存在します",
                                f"column:{col}",
                            )
                        )
                    elif col in df.columns:
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                True,
                                f"NOT NULL カラム '{col}' 正常",
                                f"column:{col}",
                            )
                        )

            elif rid == "INT-002":
                unique_cols = params.get("columns", [])
                for col in unique_cols:
                    if col in df.columns and df[col].duplicated().any():
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                False,
                                f"ユニーク制約カラム '{col}' に重複値が存在します",
                                f"column:{col}",
                            )
                        )
                    elif col in df.columns:
                        results.append(
                            make_result(
                                rid,
                                name,
                                sev,
                                True,
                                f"ユニーク制約カラム '{col}' 正常",
                                f"column:{col}",
                            )
                        )

            elif rid == "INT-003":
                expected = params.get("expected", "utf-8")
                enc = parsed.encoding.lower().replace("-", "").replace("_", "")
                exp = expected.lower().replace("-", "").replace("_", "")
                # utf-8-sig (UTF-8 with BOM, e.g. Excel output) is treated as UTF-8 compatible
                passed = enc in (exp, "ascii", f"{exp}sig", f"{exp}bom")
                msg = (
                    f"エンコーディング: {parsed.encoding}"
                    if passed
                    else f"UTF-8 以外のエンコーディング: {parsed.encoding}"
                )
                results.append(make_result(rid, name, sev, passed, msg, "file"))

        return results
