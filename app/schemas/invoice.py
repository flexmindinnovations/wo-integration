from pydantic import BaseModel, field_validator
from typing import Optional, List, Any

class InvoiceLineCreate(BaseModel):
    name: str
    quantity: float = 1.0
    price_unit: float = 0.0

class InvoiceCreate(BaseModel):
    partner_id: int
    invoice_date: Optional[str] = None
    lines: List[InvoiceLineCreate] = []

class InvoiceLineOut(BaseModel):
    id: int
    name: str
    quantity: float
    price_unit: float
    price_subtotal: float

class InvoiceOut(BaseModel):
    id: int
    name: Optional[str] = None
    partner_id: Any
    invoice_date: Any
    amount_total: float
    state: str
    payment_state: str
    invoice_line_ids: Optional[List[InvoiceLineOut]] = None

    @field_validator("name", mode="before")
    @classmethod
    def coerce_odoo_false(cls, v: Any) -> Optional[str]:
        # Odoo returns False (bool) for draft invoices with no sequence number yet
        if v is False or v is None:
            return None
        return str(v)
