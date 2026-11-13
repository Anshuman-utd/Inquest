from sqlalchemy import Connection, text

from inquest.db.fixture import TRANSACTION_COLUMNS
from inquest.scoring.features import LOOKBACK, extract_features
from inquest.synthetic.models import City, Customer, Merchant, Transaction


def transaction_features(
    connection: Connection, dataset_id: str, source_sequence: int, *, currency: str
) -> tuple[float, ...] | None:
    focal_row = (
        connection.execute(
            text(f"""
            SELECT {TRANSACTION_COLUMNS}
            FROM fixture.transactions
            WHERE dataset_id = :dataset AND source_sequence = :sequence AND currency = :currency
        """),
            {"dataset": dataset_id, "sequence": source_sequence, "currency": currency},
        )
        .mappings()
        .one_or_none()
    )
    if focal_row is None:
        return None
    focal = Transaction.model_validate(dict(focal_row))
    params = {
        "dataset": dataset_id,
        "customer": focal.customer_id,
        "merchant": focal.merchant_id,
        "device": focal.device_id,
        "sequence": focal.source_sequence,
        "currency": currency,
        "time": focal.occurred_at,
        "start": focal.occurred_at - LOOKBACK,
    }
    history_rows = connection.execute(
        text(f"""
            SELECT {TRANSACTION_COLUMNS}
            FROM fixture.transactions
            WHERE dataset_id = :dataset AND currency = :currency AND occurred_at >= :start
                AND (occurred_at, source_sequence) < (:time, :sequence)
                AND (customer_id = :customer OR merchant_id = :merchant OR device_id = :device)
            ORDER BY occurred_at, source_sequence
        """),
        params,
    ).mappings()
    customer_row = (
        connection.execute(
            text("""
            SELECT id, alias, home_city_id FROM fixture.customers
            WHERE dataset_id = :dataset AND id = :customer
        """),
            params,
        )
        .mappings()
        .one()
    )
    merchant_row = (
        connection.execute(
            text("""
            SELECT id, alias, category, city_id, risk_tier FROM fixture.merchants
            WHERE dataset_id = :dataset AND id = :merchant
        """),
            params,
        )
        .mappings()
        .one()
    )
    city_rows = connection.execute(
        text(
            "SELECT id, name, latitude, longitude FROM fixture.cities WHERE dataset_id = :dataset"
        ),
        params,
    ).mappings()
    cities = {row["id"]: City.model_validate(dict(row)) for row in city_rows}
    return extract_features(
        focal,
        Customer.model_validate(dict(customer_row)),
        Merchant.model_validate(dict(merchant_row)),
        cities,
        (Transaction.model_validate(dict(row)) for row in history_rows),
    )
