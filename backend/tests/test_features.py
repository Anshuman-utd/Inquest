import math
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from inquest.scoring.features import chronological_features, extract_features, named_features
from inquest.scoring.repository import transaction_features
from inquest.settings import Settings
from inquest.synthetic.models import City, Customer, Merchant, Transaction

NOW = datetime(2025, 2, 1, tzinfo=UTC)
CITY = City(id="pune", name="Pune", latitude=18.52, longitude=73.86)
CUSTOMER = Customer(id="c", alias="Customer", home_city_id=CITY.id)
MERCHANT = Merchant(
    id="m", alias="Merchant", city_id=CITY.id, category="retail", risk_tier="standard"
)


def payment(sequence: int, time: datetime, device_id: str = "known") -> Transaction:
    return Transaction(
        source_sequence=sequence,
        occurred_at=time,
        customer_id=CUSTOMER.id,
        merchant_id=MERCHANT.id,
        device_id=device_id,
        instrument_id="card-c",
        city_id=CITY.id,
        location_source="physical",
        amount_minor=10000,
        currency="INR",
        channel="card",
        flow="purchase",
        declined=False,
        recent_reregistration=False,
    )


def test_cutoff_includes_only_earlier_keys() -> None:
    focal = payment(3, NOW, "new")
    history = [
        payment(1, NOW - timedelta(minutes=5)),
        payment(2, NOW),
        focal,
        payment(4, NOW, "new"),
        payment(5, NOW + timedelta(seconds=1), "new"),
        payment(6, NOW - timedelta(days=31), "new"),
    ]
    values = named_features(extract_features(focal, CUSTOMER, MERCHANT, {CITY.id: CITY}, history))
    assert values["customer_count_5m"] == 2
    assert values["customer_count_30d"] == 2
    assert values["new_device_30d"] == 1
    assert values["new_merchant_30d"] == 0
    assert values["amount_history_insufficient"] == 1
    assert math.isnan(values["amount_zscore_30d"])
    assert math.isnan(values["last_physical_speed_kmh"])


@pytest.mark.skipif(os.getenv("INQUEST_TEST_POSTGRES") != "1", reason="requires seeded Postgres")
def test_batch_and_database_feature_parity() -> None:
    from hashlib import sha256
    from pathlib import Path

    from inquest.synthetic.generator import GENERATOR_VERSION, generate
    from inquest.synthetic.models import GeneratorConfig

    world = generate(GeneratorConfig.model_validate_json(Path("fixtures/india.json").read_text()))
    samples = {1, 70, 150, 1_000}
    engine = create_engine(Settings().database_url)
    try:
        with engine.connect() as connection:
            checksum = sha256(world.model_dump_json().encode()).hexdigest()
            dataset_id = f"v{GENERATOR_VERSION}-{checksum}"
            for sequence, batch in enumerate(chronological_features(world), 1):
                if sequence in samples:
                    database = transaction_features(connection, dataset_id, sequence)
                    assert database is not None
                    for actual, expected in zip(database, batch, strict=True):
                        assert (math.isnan(actual) and math.isnan(expected)) or actual == expected
                if sequence == max(samples):
                    break
    finally:
        engine.dispose()
