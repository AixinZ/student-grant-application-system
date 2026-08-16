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
