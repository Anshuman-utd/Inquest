from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from inquest.synthetic.models import Channel, City, Customer, Flow, Merchant, Transaction

MAX_HISTORY_ROWS = 20
MAX_OBSERVATION_BYTES = 16_384
TOOL_CONTRACT_VERSION: Literal["v1"] = "v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolScope(Contract):
    """Server-supplied identity, separate from tool arguments."""

    workspace_id: UUID
    analyst_id: UUID
    investigation_id: UUID


class EntityRequest(Contract):
    tool: Literal[
        "get_transaction",
        "get_customer_profile",
        "velocity_check",
        "geo_mismatch_check",
        "device_check",
        "merchant_risk_lookup",
    ]


class HistoryRequest(Contract):
    tool: Literal["get_customer_history"] = "get_customer_history"
    window_days: Annotated[int, Field(strict=True, ge=1, le=30)] = 7


DatabaseRequest = Annotated[EntityRequest | HistoryRequest, Field(discriminator="tool")]


class Cutoff(Contract):
    dataset_id: str
    occurred_at: datetime
    source_sequence: int


class TransactionObservation(Contract):
    tool: Literal["get_transaction"] = "get_transaction"
    transaction: Transaction


class Activity(Contract):
    attempts: int
    declines: int
    total_minor: int


class CustomerProfileObservation(Contract):
    tool: Literal["get_customer_profile"] = "get_customer_profile"
    customer: Customer
    home_city: City
    currency: str
    activity_30d: Activity
    first_attempt_in_window_at: datetime | None
    last_attempt_in_window_at: datetime | None
    average_amount_minor: float | None
    distinct_devices_30d: int
    distinct_merchants_30d: int


class HistoryAttempt(Contract):
    source_sequence: int
    occurred_at: datetime
    merchant_id: str
    device_id: str
    city_id: str | None
    amount_minor: int
    channel: Channel
    flow: Flow
    declined: bool


class CustomerHistoryObservation(Contract):
    tool: Literal["get_customer_history"] = "get_customer_history"
    window_days: int
    currency: str
    activity: Activity
    attempts: Annotated[tuple[HistoryAttempt, ...], Field(max_length=MAX_HISTORY_ROWS)]
    truncated: bool


class VelocityObservation(Contract):
    tool: Literal["velocity_check"] = "velocity_check"
    currency: str
    last_5m: Activity
    last_1h: Activity
    last_24h: Activity
    preceding_29d: Activity
    baseline_attempts_per_day: float


class PhysicalAttempt(Contract):
    source_sequence: int
    occurred_at: datetime
    city: City


class GeoObservation(Contract):
    tool: Literal["geo_mismatch_check"] = "geo_mismatch_check"
    location_source: Literal["physical", "remote"]
    current_city: City | None
    home_city: City
    previous_physical_30d: PhysicalAttempt | None
    distance_from_home_km: float | None
    distance_since_previous_km: float | None
    elapsed_seconds: float | None
    implied_speed_kmh: float | None


class DeviceObservation(Contract):
    tool: Literal["device_check"] = "device_check"
    device_id: str
    recent_reregistration: bool
    first_attempt_in_window_at: datetime | None
    last_attempt_in_window_at: datetime | None
    device_attempts_30d: int
    customer_attempts_on_device_30d: int
    customer_attempts_30d: int
    distinct_customers_1h: int
    distinct_instruments_1h: int


class MerchantObservation(Contract):
    tool: Literal["merchant_risk_lookup"] = "merchant_risk_lookup"
    merchant: Merchant
    currency: str
    activity_30d: Activity
    customer_attempts_at_merchant_30d: int
    distinct_customers_5m: int
    upi_push_attempts_5m: int
    same_amount_attempts_24h: int


DatabaseObservation = Annotated[
    TransactionObservation
    | CustomerProfileObservation
    | CustomerHistoryObservation
    | VelocityObservation
    | GeoObservation
    | DeviceObservation
    | MerchantObservation,
    Field(discriminator="tool"),
]


class Evidence(Contract):
    evidence_id: UUID
    investigation_id: UUID
    call_sequence: int
    cutoff: Cutoff
    contract_version: Literal["v1"] = TOOL_CONTRACT_VERSION


class DatabaseEvidence(Evidence):
    status: Literal["ok"] = "ok"
    observation: DatabaseObservation


class UnavailableEvidence(Evidence):
    status: Literal["unavailable"] = "unavailable"
    tool: str
    reason: Literal["data_unavailable", "observation_too_large"]
