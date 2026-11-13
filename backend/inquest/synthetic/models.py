from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal["card", "upi"]
Flow = Literal["purchase", "push", "collect"]
RiskTier = Literal["standard", "elevated"]
Scenario = Literal[
    "account_takeover",
    "card_testing",
    "velocity_burst",
    "impossible_travel",
    "new_device_high_value",
    "mule_cash_out",
    "merchant_collusion",
    "upi_collect_scam",
    "upi_sim_swap",
]


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class City(FixtureModel):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    name: Annotated[str, Field(min_length=1)]
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class AmountDistribution(FixtureModel):
    category: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    median_minor: Annotated[int, Field(gt=0, le=100_000_000)]
    log_sigma: Annotated[float, Field(gt=0, le=2)]
    weight: Annotated[float, Field(gt=0, le=100)]


class GeneratorConfig(FixtureModel):
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    start: datetime
    days: Annotated[int, Field(ge=30, le=366)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    timezone: str
    customer_count: Annotated[int, Field(ge=30, le=10_000)]
    merchant_count: Annotated[int, Field(ge=1, le=2_000)]
    attempts_per_customer_week: Annotated[float, Field(ge=0.5, le=12)]
    fraud_rate: Annotated[float, Field(gt=0, le=0.02)]
    lookalikes_per_fraud_episode: Annotated[int, Field(ge=1, le=10)]
    cities: Annotated[tuple[City, ...], Field(min_length=2)]
    amounts: Annotated[tuple[AmountDistribution, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def validate_world(self) -> Self:
        if self.start.utcoffset() != UTC.utcoffset(None):
            raise ValueError("start must have a UTC offset")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must name an IANA time zone") from exc
        if len({city.id for city in self.cities}) != len(self.cities):
            raise ValueError("city IDs must be unique")
        categories = {amount.category for amount in self.amounts}
        if len(categories) != len(self.amounts):
            raise ValueError("amount categories must be unique")
        if not {"transfer", "cash_like"} <= categories or len(categories) < 4:
            raise ValueError("include transfer, cash_like and at least two purchase categories")
        if self.merchant_count < len(categories):
            raise ValueError("merchant_count must cover all amount categories")
        return self


class Customer(FixtureModel):
    id: str
    alias: str
    home_city_id: str


class Merchant(FixtureModel):
    id: str
    alias: str
    category: str
    city_id: str
    risk_tier: RiskTier


class Device(FixtureModel):
    id: str


class Payment(FixtureModel):
    customer_id: str
    merchant_id: str
    device_id: str
    instrument_id: str
    city_id: str | None
    location_source: Literal["physical", "remote"]
    occurred_at: datetime
    amount_minor: Annotated[int, Field(gt=0)]
    currency: str
    channel: Channel
    flow: Flow
    declined: bool
    recent_reregistration: bool


class Transaction(Payment):
    source_sequence: Annotated[int, Field(gt=0)]


class Truth(FixtureModel):
    source_sequence: int
    is_fraud: bool
    scenario: Scenario | None
    episode_id: str | None


class World(FixtureModel):
    config: GeneratorConfig
    customers: tuple[Customer, ...]
    merchants: tuple[Merchant, ...]
    devices: tuple[Device, ...]
    transactions: tuple[Transaction, ...]
    truth: tuple[Truth, ...]
