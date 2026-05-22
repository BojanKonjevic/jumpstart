from pathlib import Path

from zenit.schema.models import AddonConfig, FileContribution

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="sqlmodel",
    description="SQLModel ORM (Pydantic + SQLAlchemy)",
    requires=["sqlalchemy"],
    templates=["fastapi"],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/models/base.py",
            source=str(_HERE / "files" / "src" / "{{pkg_name}}" / "models" / "base.py"),
        ),
    ],
    deps=[
        "sqlmodel",
    ],
)
