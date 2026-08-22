"""Typed models for the workbook entities. Fields match
docs/data_dictionary.md exactly - no invented columns.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus, TicketStatus


class Account(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    account_name: str
    plan: str
    status: str
    csm: str
    contract_file: str | None
    premium_support: bool
    notes: str


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    account_id: str
    carrier: str
    status: OrderStatus
    booked_at: datetime
    pickup_window_start: datetime
    pickup_window_end: datetime
    pickup_actual_at: datetime | None
    shipment_fee_inr: float
    carrier_fault: bool
    customer_fault: bool
    cancellation_requested_at: datetime | None
    notes: str


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    account_id: str
    created_at: datetime
    status: TicketStatus
    subject: str
    description: str
    channel: str
    assigned_to: str
    last_customer_message_at: datetime
    historical_resolution: str | None
