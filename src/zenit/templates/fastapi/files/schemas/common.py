from pydantic import BaseModel


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
