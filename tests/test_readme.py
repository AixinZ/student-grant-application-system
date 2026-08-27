from pathlib import Path


README_PATH = Path(__file__).parents[1] / "README.md"
DEFAULT_DATABASE_PATH = "instance/student_grants.sqlite"
CUSTOM_DATABASE_URL = "sqlite:////absolute/path/to/student_grants.sqlite"
CUSTOM_DATABASE_PATH = "/absolute/path/to/student_grants.sqlite"


def read_section(markdown: str, heading: str) -> str:
    marker = f"## {heading}\n"
    section = markdown.split(marker, 1)[1]
    return section.split("\n## ", 1)[0]


# Protected mutation: hardcoding the default instance path in backup or restore
# would direct a custom-DATABASE_URL operator to copy the wrong SQLite file.
def test_database_operations_follow_the_configured_sqlite_file():
    readme = README_PATH.read_text(encoding="utf-8")
    configuration = read_section(readme, "Local secret and configuration")
    backup = read_section(readme, "Backup")
    recovery = read_section(readme, "Restore and recovery")

    assert CUSTOM_DATABASE_URL in configuration
    assert f"`{CUSTOM_DATABASE_PATH}`" in configuration.replace(
        f"`{CUSTOM_DATABASE_URL}`", ""
    )
    for operation_section in (backup, recovery):
        normalized = " ".join(operation_section.lower().split())
        assert "configured" in normalized
        assert "database file" in normalized
        assert DEFAULT_DATABASE_PATH not in operation_section

    for paragraph in readme.split("\n\n"):
        if DEFAULT_DATABASE_PATH in paragraph:
            assert "default" in paragraph.lower()


def test_readme_documents_csv_scoring_operator_contract():
    """Catch an operator guide that omits CSV scoring's safety boundaries."""
    readme = README_PATH.read_text(encoding="utf-8").lower()

    for required_text in (
        "http://127.0.0.1:5000/csv-scoring",
        "100 mb",
        "100,000 through 250,000",
        "utf-8 with bom",
        "six decimal places",
        "low risk at `0` and high risk at `1`",
        "one hour",
        "experimental isolation forest",
        "not proof of fraud",
        "csv_scoring_model_dir",
    ):
        assert required_text in readme
