from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from math import asin, cos, log1p, radians, sin, sqrt
from statistics import mean, stdev

from inquest.synthetic.models import City, Customer, Merchant, Transaction, World

FEATURE_VERSION = "v1"
LOOKBACK = timedelta(days=30)
WINDOWS = (("5m", timedelta(minutes=5)), ("1h", timedelta(hours=1)), ("24h", timedelta(days=1)))
FEATURE_NAMES = (
    "log_amount",
    "upi",
    "collect",
    "declined",
    "recent_reregistration",
    "elevated_merchant",
    "cash_like",
    "transfer",
    "hour_sin",
    "hour_cos",
    "location_known",
    "home_distance_km",
    "last_physical_distance_km",
    "last_physical_elapsed_hours",
    "last_physical_speed_kmh",
    "customer_count_30d",
    "amount_zscore_30d",
    "amount_history_insufficient",
    "new_device_30d",
    "new_merchant_30d",
    "instrument_device_novel_30d",
    "log_amount_vs_merchant_30d",
    "merchant_same_amount_24h",
    "device_distinct_customers_1h",
    "device_distinct_instruments_1h",
    "merchant_distinct_customers_1h",
    *(
        f"{metric}_{window}"
        for window, _ in WINDOWS
        for metric in (
            "customer_count",
            "customer_declines",
            "customer_log_total",
            "merchant_count",
            "device_count",
            "device_declines",
        )
    ),
)


def event_key(transaction: Transaction) -> tuple[datetime, int]:
    return transaction.occurred_at, transaction.source_sequence


def distance_km(first: City, second: City) -> float:
    lat1, lat2 = radians(first.latitude), radians(second.latitude)
    delta_lon = radians(second.longitude - first.longitude)
    haversine = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 12_742 * asin(sqrt(min(1.0, haversine)))


def extract_features(
    focal: Transaction,
    customer: Customer,
    merchant: Merchant,
    cities: Mapping[str, City],
    history: Iterable[Transaction],
) -> tuple[float, ...]:
    cutoff = event_key(focal)
    lower_bound = focal.occurred_at - LOOKBACK
    prior = [
        item for item in history if lower_bound <= item.occurred_at and event_key(item) < cutoff
    ]
    customer_history = [item for item in prior if item.customer_id == focal.customer_id]
    merchant_history = [item for item in prior if item.merchant_id == focal.merchant_id]
    device_history = [item for item in prior if item.device_id == focal.device_id]
    log_amount = log1p(focal.amount_minor)
    amounts = [log1p(item.amount_minor) for item in customer_history]
    deviation = stdev(amounts) if len(amounts) >= 3 else 0.0

    location = cities.get(focal.city_id) if focal.city_id else None
    last_physical = max(
        (item for item in customer_history if item.city_id is not None),
        key=event_key,
        default=None,
    )
    last_distance = elapsed = speed = float("nan")
    if location is not None and last_physical is not None and last_physical.city_id is not None:
        last_distance = distance_km(location, cities[last_physical.city_id])
        elapsed = (focal.occurred_at - last_physical.occurred_at).total_seconds() / 3600
        if elapsed > 0:
            speed = last_distance / elapsed

    hour_angle = focal.occurred_at.astimezone(UTC).hour / 24 * radians(360)
    last_day = focal.occurred_at - timedelta(days=1)
    last_hour = focal.occurred_at - timedelta(hours=1)
    values = [
        log_amount,
        float(focal.channel == "upi"),
        float(focal.flow == "collect"),
        float(focal.declined),
        float(focal.recent_reregistration),
        float(merchant.risk_tier == "elevated"),
        float(merchant.category == "cash_like"),
        float(merchant.category == "transfer"),
        sin(hour_angle),
        cos(hour_angle),
        float(location is not None),
        distance_km(location, cities[customer.home_city_id]) if location else float("nan"),
        last_distance,
        elapsed,
        speed,
        float(len(amounts)),
        (log_amount - mean(amounts)) / deviation if deviation > 0 else float("nan"),
        float(deviation == 0),
        float(not any(item.device_id == focal.device_id for item in customer_history)),
        float(not any(item.merchant_id == focal.merchant_id for item in customer_history)),
        float(not any(item.instrument_id == focal.instrument_id for item in device_history)),
        log_amount - mean(log1p(item.amount_minor) for item in merchant_history)
        if merchant_history
        else float("nan"),
        float(
            sum(
                item.amount_minor == focal.amount_minor and item.occurred_at >= last_day
                for item in merchant_history
            )
        ),
        float(len({item.customer_id for item in device_history if item.occurred_at >= last_hour})),
        float(
            len({item.instrument_id for item in device_history if item.occurred_at >= last_hour})
        ),
        float(
            len({item.customer_id for item in merchant_history if item.occurred_at >= last_hour})
        ),
    ]
    for _, duration in WINDOWS:
        start = focal.occurred_at - duration
        customer_window = [item for item in customer_history if item.occurred_at >= start]
        device_window = [item for item in device_history if item.occurred_at >= start]
        values.extend(
            (
                float(len(customer_window)),
                float(sum(item.declined for item in customer_window)),
                log1p(sum(item.amount_minor for item in customer_window)),
                float(sum(item.occurred_at >= start for item in merchant_history)),
                float(len(device_window)),
                float(sum(item.declined for item in device_window)),
            )
        )
    return tuple(values)


def chronological_features(world: World) -> Iterator[tuple[float, ...]]:
    customers = {customer.id: customer for customer in world.customers}
    merchants = {merchant.id: merchant for merchant in world.merchants}
    cities = {city.id: city for city in world.config.cities}
    histories: dict[tuple[str, str], deque[Transaction]] = defaultdict(deque)
    previous: tuple[datetime, int] | None = None
    for transaction in world.transactions:
        key = event_key(transaction)
        if previous is not None and key <= previous:
            raise ValueError("transactions must be strictly ordered by event time and sequence")
        previous = key
        buckets = (
            histories["customer", transaction.customer_id],
            histories["merchant", transaction.merchant_id],
            histories["device", transaction.device_id],
        )
        lower_bound = transaction.occurred_at - LOOKBACK
        history: dict[int, Transaction] = {}
        for bucket in buckets:
            while bucket and bucket[0].occurred_at < lower_bound:
                bucket.popleft()
            history.update((item.source_sequence, item) for item in bucket)
        yield extract_features(
            transaction,
            customers[transaction.customer_id],
            merchants[transaction.merchant_id],
            cities,
            sorted(history.values(), key=event_key),
        )
        for bucket in buckets:
            bucket.append(transaction)


def named_features(values: Sequence[float]) -> dict[str, float]:
    return dict(zip(FEATURE_NAMES, values, strict=True))
