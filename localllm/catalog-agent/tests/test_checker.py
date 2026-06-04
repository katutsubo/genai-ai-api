import pandas as pd
import pytest
from agent.checker.csv_checker import CSVChecker
from agent.models import ParsedData


@pytest.fixture
def checker():
    return CSVChecker()


def make_parsed(df: pd.DataFrame, encoding: str = "utf-8") -> ParsedData:
    return ParsedData(file_path="test.csv", file_type="csv", df=df, encoding=encoding)


def test_str001_required_columns_pass(checker):
    df = pd.DataFrame({"id": [1], "name": ["a"]})
    results = checker.check(make_parsed(df))
    str001 = next(r for r in results if r.rule_id == "STR-001")
    assert str001.passed


def test_str001_required_columns_fail(checker, tmp_path):
    # temporarily patch rules to require a column
    import os

    import yaml

    rules_path = os.path.join(os.path.dirname(__file__), "../rules/rules_csv.yaml")
    with open(rules_path) as f:
        rules = yaml.safe_load(f)
    for rule in rules["rules"]:
        if rule["id"] == "STR-001":
            rule["params"]["columns"] = ["missing_col"]

    tmp_rules = tmp_path / "rules.yaml"
    with open(tmp_rules, "w") as f:
        yaml.dump(rules, f)

    from agent.checker.csv_checker import CSVChecker as C

    c = C(rules_path=str(tmp_rules))
    df = pd.DataFrame({"id": [1]})
    results = c.check(make_parsed(df))
    str001 = next(r for r in results if r.rule_id == "STR-001")
    assert not str001.passed
    assert str001.severity == "error"
    assert "missing_col" in str001.location


def test_str002_column_name_format(checker):
    df = pd.DataFrame({"BadColumn": [1], "good_col": [2]})
    results = checker.check(make_parsed(df))
    str002 = [r for r in results if r.rule_id == "STR-002"]
    failed = [r for r in str002 if not r.passed]
    assert any("BadColumn" in r.location for r in failed)


def test_typ001_date_column_format_pass(checker):
    df = pd.DataFrame({"created_date": ["2024-01-01", "2024-12-31"]})
    results = checker.check(make_parsed(df))
    typ001 = [r for r in results if r.rule_id == "TYP-001"]
    failed = [r for r in typ001 if not r.passed]
    assert len(failed) == 0


def test_typ001_date_column_format_fail(checker):
    df = pd.DataFrame({"created_date": ["01/01/2024", "bad"]})
    results = checker.check(make_parsed(df))
    typ001 = [r for r in results if r.rule_id == "TYP-001" and not r.passed]
    assert len(typ001) > 0
    assert typ001[0].severity == "error"


def test_typ002_numeric_column_type(checker):
    df = pd.DataFrame({"user_id": ["not_a_number", "also_not"]})
    results = checker.check(make_parsed(df))
    typ002 = [r for r in results if r.rule_id == "TYP-002" and not r.passed]
    assert len(typ002) > 0
    assert typ002[0].severity == "warning"


def test_int001_not_null_pass(checker):
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    results = checker.check(make_parsed(df))
    int001 = [r for r in results if r.rule_id == "INT-001"]
    failed = [r for r in int001 if not r.passed]
    assert len(failed) == 0


def test_int002_unique_columns(checker, tmp_path):
    import os

    import yaml

    rules_path = os.path.join(os.path.dirname(__file__), "../rules/rules_csv.yaml")
    with open(rules_path) as f:
        rules = yaml.safe_load(f)
    for rule in rules["rules"]:
        if rule["id"] == "INT-002":
            rule["params"]["columns"] = ["id"]
    tmp_rules = tmp_path / "rules.yaml"
    with open(tmp_rules, "w") as f:
        yaml.dump(rules, f)

    from agent.checker.csv_checker import CSVChecker as C

    c = C(rules_path=str(tmp_rules))
    df = pd.DataFrame({"id": [1, 1]})
    results = c.check(make_parsed(df))
    int002 = [r for r in results if r.rule_id == "INT-002" and not r.passed]
    assert len(int002) > 0
    assert int002[0].severity == "warning"


def test_int003_encoding_utf8_pass(checker):
    df = pd.DataFrame({"a": [1]})
    results = checker.check(make_parsed(df, encoding="utf-8"))
    int003 = next(r for r in results if r.rule_id == "INT-003")
    assert int003.passed
    assert int003.severity == "info"


def test_int003_encoding_shiftjis_warn(checker):
    df = pd.DataFrame({"a": [1]})
    results = checker.check(make_parsed(df, encoding="shift_jis"))
    int003 = next(r for r in results if r.rule_id == "INT-003")
    assert not int003.passed
    assert int003.severity == "info"
