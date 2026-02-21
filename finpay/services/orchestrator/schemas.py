"""API request/response schemas for orchestrator endpoints."""

from pydantic import BaseModel, Field


class PaymentCreateRequest(BaseModel):
    """Payment creation payload accepted from gateway."""

    customer_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=5)


class PaymentResponse(BaseModel):
    """Minimal payment response returned to clients/services."""

    payment_id: str
    status: str
