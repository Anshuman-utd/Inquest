from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.engine import RowMapping

from inquest.db.fixture import TRANSACTION_COLUMNS
from inquest.investigation.contracts import (
    MAX_HISTORY_ROWS,
    Activity,
    CustomerHistoryObservation,
    CustomerProfileObservation,
    Cutoff,
    DeviceObservation,
    GeoObservation,
    HistoryAttempt,
    MerchantObservation,
    PhysicalAttempt,
    VelocityObservation,
)
from inquest.scoring.features import LOOKBACK, distance_km
from inquest.synthetic.models import City, Customer, Merchant, Transaction

# Every aggregate and detail query uses this same cutoff.
PRIOR = """
    dataset_id = :dataset AND currency = :currency
    AND source_sequence < :sequence
    AND occurred_at >= :start AND (occurred_at, source_sequence) < (:time, :sequence)
"""
TOTALS = """
    count(*) AS attempts, count(*) FILTER (WHERE declined) AS declines,
    coalesce(sum(amount_minor), 0) AS total_minor
"""


class InvestigationUnavailable(Exception):
    """The scoped investigation or its replay position is unavailable."""


def resolve_case(connection: Connection, workspace_id: UUID, investigation_id: UUID) -> Cutoff:
    row = connection.execute(
        text("""
            SELECT c.dataset_id, c.source_sequence, t.occurred_at
            FROM operations.investigations AS i
            JOIN operations.cases AS c ON (c.workspace_id, c.id) = (i.workspace_id, i.case_id)
            JOIN operations.replay_runs AS r ON (r.id, r.dataset_id) = (c.replay_id, c.dataset_id)
            JOIN fixture.transactions AS t
                ON (t.dataset_id, t.source_sequence) = (c.dataset_id, c.source_sequence)
            WHERE i.workspace_id = :workspace AND i.id = :investigation
                AND c.source_sequence <= r.cursor
        """),
        {"workspace": workspace_id, "investigation": investigation_id},
    ).one_or_none()
    if row is None:
        raise InvestigationUnavailable
    return Cutoff(
        dataset_id=row.dataset_id,
        source_sequence=row.source_sequence,
        occurred_at=row.occurred_at.astimezone(UTC),
    )


def focal_transaction(connection: Connection, position: Cutoff) -> Transaction:
    row = (
        connection.execute(
            text(f"""
                SELECT {TRANSACTION_COLUMNS}
                FROM fixture.transactions
                WHERE dataset_id = :dataset AND source_sequence = :sequence
            """),
            {"dataset": position.dataset_id, "sequence": position.source_sequence},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InvestigationUnavailable
    return Transaction.model_validate(dict(row))


class Observations:
    """Read evidence at the focal transaction's immutable event key."""

    def __init__(self, connection: Connection, position: Cutoff, focal: Transaction) -> None:
        self._connection = connection
        self.focal = focal
        self._params = {
            "dataset": position.dataset_id,
            "sequence": position.source_sequence,
            "time": focal.occurred_at,
            "start": focal.occurred_at - LOOKBACK,
            "currency": focal.currency,
            "customer": focal.customer_id,
            "merchant": focal.merchant_id,
            "device": focal.device_id,
        }

    def _one(self, query: str, **params: Any) -> RowMapping:
        return self._connection.execute(text(query), self._params | params).mappings().one()

    def _customer(self) -> Customer:
        row = self._one("""
            SELECT id, alias, home_city_id FROM fixture.customers
            WHERE dataset_id = :dataset AND id = :customer
        """)
        return Customer.model_validate(dict(row))

    def _city(self, city_id: str) -> City:
        row = self._one(
            """
            SELECT id, name, latitude, longitude FROM fixture.cities
            WHERE dataset_id = :dataset AND id = :city
        """,
            city=city_id,
        )
        return City.model_validate(dict(row))

    def _before(self, delta: timedelta) -> datetime:
        return self.focal.occurred_at - delta

    def customer_profile(self) -> CustomerProfileObservation:
        customer = self._customer()
        summary = self._one(f"""
            SELECT {TOTALS}, min(occurred_at) AS first_at, max(occurred_at) AS last_at,
                count(DISTINCT device_id) AS devices, count(DISTINCT merchant_id) AS merchants
            FROM fixture.transactions WHERE {PRIOR} AND customer_id = :customer
        """)
        count = summary["attempts"]
        return CustomerProfileObservation(
            customer=customer,
            home_city=self._city(customer.home_city_id),
            currency=self.focal.currency,
            activity_30d=activity(summary),
            first_attempt_in_window_at=summary["first_at"],
            last_attempt_in_window_at=summary["last_at"],
            average_amount_minor=float(summary["total_minor"] / count) if count else None,
            distinct_devices_30d=summary["devices"],
            distinct_merchants_30d=summary["merchants"],
        )

    def customer_history(self, window_days: int) -> CustomerHistoryObservation:
        start = self._before(timedelta(days=window_days))
        summary = self._one(
            f"""
            SELECT {TOTALS}
            FROM fixture.transactions WHERE {PRIOR} AND customer_id = :customer
        """,
            start=start,
        )
        rows = self._connection.execute(
            text(f"""
                SELECT source_sequence, occurred_at, merchant_id, device_id, city_id,
                    amount_minor, channel, flow, declined
                FROM fixture.transactions WHERE {PRIOR} AND customer_id = :customer
                ORDER BY occurred_at DESC, source_sequence DESC LIMIT :limit
            """),
            self._params | {"start": start, "limit": MAX_HISTORY_ROWS},
        ).mappings()
        attempts = tuple(HistoryAttempt.model_validate(dict(row)) for row in rows)
        return CustomerHistoryObservation(
            window_days=window_days,
            currency=self.focal.currency,
            activity=activity(summary),
            attempts=attempts,
            truncated=summary["attempts"] > len(attempts),
        )

    def velocity(self) -> VelocityObservation:
        totals = []
        # Four disjoint bands in one bounded index scan. Add bands to build trailing windows.
        rows = self._connection.execute(
            text(f"""
                SELECT CASE WHEN occurred_at >= :five_minutes THEN 0
                    WHEN occurred_at >= :one_hour THEN 1
                    WHEN occurred_at >= :one_day THEN 2 ELSE 3 END AS band, {TOTALS}
                FROM fixture.transactions WHERE {PRIOR} AND customer_id = :customer
                GROUP BY band
            """),
            self._params
            | {
                "five_minutes": self._before(timedelta(minutes=5)),
                "one_hour": self._before(timedelta(hours=1)),
                "one_day": self._before(timedelta(days=1)),
            },
        ).mappings()
        by_band = {row["band"]: activity(row) for row in rows}
        cumulative = Activity(attempts=0, declines=0, total_minor=0)
        for band in range(3):
            if (current := by_band.get(band)) is not None:
                cumulative = Activity(
                    attempts=cumulative.attempts + current.attempts,
                    declines=cumulative.declines + current.declines,
                    total_minor=cumulative.total_minor + current.total_minor,
                )
            totals.append(cumulative)
        baseline = by_band.get(3, Activity(attempts=0, declines=0, total_minor=0))
        return VelocityObservation(
            currency=self.focal.currency,
            last_5m=totals[0],
            last_1h=totals[1],
            last_24h=totals[2],
            preceding_29d=baseline,
            baseline_attempts_per_day=baseline.attempts / 29,
        )

    def geography(self) -> GeoObservation:
        home = self._city(self._customer().home_city_id)
        current = self._city(self.focal.city_id) if self.focal.city_id is not None else None
        row = (
            self._connection.execute(
                text(f"""
                    SELECT source_sequence, occurred_at, city_id
                    FROM fixture.transactions
                    WHERE {PRIOR} AND customer_id = :customer AND location_source = 'physical'
                    ORDER BY occurred_at DESC, source_sequence DESC LIMIT 1
                """),
                self._params,
            )
            .mappings()
            .one_or_none()
        )
        previous = None
        elapsed = distance = speed = None
        if row is not None:
            previous = PhysicalAttempt(
                source_sequence=row["source_sequence"],
                occurred_at=row["occurred_at"],
                city=self._city(row["city_id"]),
            )
            elapsed = (self.focal.occurred_at - previous.occurred_at).total_seconds()
            if current is not None:
                distance = distance_km(previous.city, current)
                speed = distance * 3600 / elapsed if elapsed > 0 else None
        return GeoObservation(
            location_source=self.focal.location_source,
            current_city=current,
            home_city=home,
            previous_physical_30d=previous,
            distance_from_home_km=distance_km(home, current) if current is not None else None,
            distance_since_previous_km=distance,
            elapsed_seconds=elapsed,
            implied_speed_kmh=speed,
        )

    def device(self) -> DeviceObservation:
        history = self._one(
            f"""
            SELECT min(occurred_at) AS first_at, max(occurred_at) AS last_at,
                count(*) AS device_attempts,
                count(*) FILTER (WHERE customer_id = :customer) AS customer_on_device,
                count(DISTINCT customer_id) FILTER (WHERE occurred_at >= :one_hour) AS customers,
                count(DISTINCT instrument_id) FILTER (WHERE occurred_at >= :one_hour) AS instruments
            FROM fixture.transactions WHERE {PRIOR} AND device_id = :device
        """,
            one_hour=self._before(timedelta(hours=1)),
        )
        customer = self._one(f"""
            SELECT count(*) AS attempts FROM fixture.transactions
            WHERE {PRIOR} AND customer_id = :customer
        """)
        return DeviceObservation(
            device_id=self.focal.device_id,
            recent_reregistration=self.focal.recent_reregistration,
            first_attempt_in_window_at=history["first_at"],
            last_attempt_in_window_at=history["last_at"],
            device_attempts_30d=history["device_attempts"],
            customer_attempts_on_device_30d=history["customer_on_device"],
            customer_attempts_30d=customer["attempts"],
            distinct_customers_1h=history["customers"],
            distinct_instruments_1h=history["instruments"],
        )

    def merchant(self) -> MerchantObservation:
        merchant = self._one("""
            SELECT id, alias, category, city_id, risk_tier FROM fixture.merchants
            WHERE dataset_id = :dataset AND id = :merchant
        """)
        summary = self._one(
            f"""
            SELECT {TOTALS},
                count(*) FILTER (WHERE customer_id = :customer) AS familiar,
                count(DISTINCT customer_id) FILTER (WHERE occurred_at >= :five_minutes) AS senders,
                count(*) FILTER (
                    WHERE occurred_at >= :five_minutes AND channel = 'upi' AND flow = 'push'
                ) AS pushes,
                count(*) FILTER (
                    WHERE occurred_at >= :one_day AND amount_minor = :amount
                ) AS same_amount
            FROM fixture.transactions WHERE {PRIOR} AND merchant_id = :merchant
        """,
            five_minutes=self._before(timedelta(minutes=5)),
            one_day=self._before(timedelta(days=1)),
            amount=self.focal.amount_minor,
        )
        return MerchantObservation(
            merchant=Merchant.model_validate(dict(merchant)),
            currency=self.focal.currency,
            activity_30d=activity(summary),
            customer_attempts_at_merchant_30d=summary["familiar"],
            distinct_customers_5m=summary["senders"],
            upi_push_attempts_5m=summary["pushes"],
            same_amount_attempts_24h=summary["same_amount"],
        )


def activity(row: RowMapping) -> Activity:
    return Activity(
        attempts=row["attempts"], declines=row["declines"], total_minor=int(row["total_minor"])
    )
