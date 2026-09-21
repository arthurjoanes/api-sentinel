from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MoneyCents = Annotated[
    int, Field(strict=True, ge=0, description="Valor inteiro em centavos de BRL.")
]


class Coverage(BaseModel):
    starts_on: str = Field(description="Primeiro dia coberto, em America/Sao_Paulo (YYYY-MM-DD).")
    ends_on: str = Field(description="Último dia coberto, inclusive (YYYY-MM-DD).")


class CompleteCoverage(Coverage):
    complete: Literal[True]


class Store(BaseModel):
    id: int
    name: str
    coverage: Coverage


class StoreList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Store]


class StoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: int
    start: str
    end: str
    currency: Literal["BRL"]
    revenue_cents: MoneyCents
    order_count: int = Field(ge=0, description="Pedidos distintos da loja, não linhas de itens.")
    average_ticket_cents: MoneyCents
    data_updated_at: str = Field(description="Instante dos dados; permanece igual no cache hit.")
    observed_at: str = Field(description="Instante do cálculo; permanece igual no cache hit.")
    dataset_version: str
    coverage: CompleteCoverage
    cache_age_seconds: float = Field(ge=0, description="Idade do cálculo, em segundos.")


class SaleItem(BaseModel):
    id: int
    order_id: int
    sold_at: str = Field(description="Instante UTC da venda, com fuso explícito.")
    sku: str
    quantity: int = Field(gt=0)
    unit_price_cents: MoneyCents
    line_total_cents: MoneyCents


class SalesPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SaleItem] = Field(max_length=100)
    next_cursor: str | None = Field(
        description="Reutilize com a mesma loja e período; null encerra a paginação."
    )
    dataset_version: str
    data_updated_at: str
    coverage: CompleteCoverage


class ProblemDocument(BaseModel):
    type: str
    title: str
    status: int
    code: str = Field(description="Código do erro.")
    request_id: str = Field(description="ID da requisição nos logs.")


BUSINESS_ERRORS: dict[int | str, dict[str, object]] = {
    status: {
        "description": description,
        "content": {"application/problem+json": {"schema": ProblemDocument.model_json_schema()}},
    }
    for status, description in (
        (401, "Credencial ausente, inválida, expirada ou revogada."),
        (403, "Loja ou operação não permitida à credencial."),
        (404, "Loja ou dados indisponíveis."),
        (422, "Parâmetro, período, cobertura ou cursor inválido."),
        (429, "Quota contratada excedida; respeite Retry-After."),
        (503, "Capacidade ou dependência indisponível; respeite Retry-After quando presente."),
    )
}
