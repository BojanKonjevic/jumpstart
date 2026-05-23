# sqlmodel

SQLModel ORM, combining Pydantic and SQLAlchemy into a single model system.

---

## When to use it

Choose `sqlmodel` when you prefer SQLModel's unified model approach over separate Pydantic schemas and SQLAlchemy models. SQLModel models act as both database models and Pydantic schemas, reducing the boilerplate of maintaining separate layers.

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `my_project/models/base.py` | SQLModel `SQLModel` base |

### Dependencies

| Package | Purpose |
|---|---|
| `sqlmodel` | SQLModel ORM (includes Pydantic + SQLAlchemy) |

---

## Compatibility

Requires the `sqlalchemy` addon and the `fastapi` template. Not compatible with `blank`.

> [!NOTE]
> `sqlmodel` provides only the model base class. The database session, migrations, and driver setup come from the `sqlalchemy` and `postgres` addons.
