from pydantic import BaseModel
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
    name: str
    partner_id: Any
    invoice_date: Any
    amount_total: float
    state: str
    payment_state: str
    invoice_line_ids: Optional[List[InvoiceLineOut]] = None
