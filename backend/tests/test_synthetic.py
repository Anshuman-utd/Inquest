from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

from inquest.synthetic.generator import SCENARIO_LENGTHS, generate
from inquest.synthetic.models import GeneratorConfig, Transaction, World

CONFIG = Path("fixtures/india.json")


@pytest.fixture(scope="module")
def config() -> GeneratorConfig:
    return GeneratorConfig.model_validate_json(CONFIG.read_text())


@pytest.fixture(scope="module")
def world(config: GeneratorConfig) -> World:
    return generate(config)


def test_seed_reproducibility(config: GeneratorConfig, world: World) -> None:
    assert generate(config).model_dump_json() == world.model_dump_json()
    changed = config.model_copy(update={"seed": config.seed + 1})
    assert generate(changed).transactions != world.transactions


def test_order_and_references(world: World) -> None:
    assert len(world.transactions) == len(world.truth)
    assert len(world.transactions) > 30_000
    customers = {item.id for item in world.customers}
    merchants = {item.id for item in world.merchants}
    devices = {item.id for item in world.devices}
    cities = {item.id for item in world.config.cities}
    previous = world.config.start
    end = world.config.start + timedelta(days=world.config.days)
    for sequence, (transaction, truth) in enumerate(
        zip(world.transactions, world.truth, strict=True), 1
    ):
        assert transaction.source_sequence == truth.source_sequence == sequence
        assert previous <= transaction.occurred_at < end
        previous = transaction.occurred_at
        assert transaction.customer_id in customers
        assert transaction.merchant_id in merchants
        assert transaction.device_id in devices
        assert (transaction.city_id in cities) == (transaction.location_source == "physical")
        assert transaction.currency == "INR"
        assert transaction.amount_minor > 0
        assert (transaction.flow == "purchase") == (transaction.channel == "card")
        assert not {"is_fraud", "scenario", "episode_id"} & transaction.model_dump().keys()


def test_scenarios_have_legitimate_lookalikes(world: World) -> None:
    assert 0.0045 < sum(item.is_fraud for item in world.truth) / len(world.truth) < 0.0055
    fraud_episodes = {item.episode_id for item in world.truth if item.is_fraud}
    assert {item.scenario for item in world.truth if item.is_fraud} == set(SCENARIO_LENGTHS)
    assert {
        item.scenario
        for item in world.truth
        if item.episode_id is not None and item.episode_id not in fraud_episodes
    } == set(SCENARIO_LENGTHS)


def test_upi_and_card_testing_signals(world: World) -> None:
    episodes: dict[str, list[Transaction]] = defaultdict(list)
    for transaction, truth in zip(world.transactions, world.truth, strict=True):
        if truth.scenario == "upi_collect_scam":
            assert transaction.channel == "upi" and transaction.flow == "collect"
        if truth.scenario == "upi_sim_swap":
            assert transaction.channel == "upi" and transaction.recent_reregistration
        if truth.scenario in {"mule_cash_out", "card_testing"}:
            assert truth.episode_id is not None
            if truth.scenario == "mule_cash_out":
                assert transaction.channel == "upi" and transaction.flow == "push"
            else:
                assert transaction.channel == "card"
            episodes[truth.episode_id].append(transaction)
    for attempts in episodes.values():
        assert len({item.merchant_id for item in attempts}) == 1
        assert attempts[-1].occurred_at - attempts[0].occurred_at < timedelta(minutes=10)
    assert any(len({item.instrument_id for item in attempts}) > 1 for attempts in episodes.values())


def test_currency_and_geography_are_configurable(config: GeneratorConfig) -> None:
    overrides = {"currency": "USD", "cities": config.cities[:2], "customer_count": 30, "days": 30}
    world = generate(config.model_copy(update=overrides))
    assert {item.currency for item in world.transactions} == {"USD"}
    assert {item.home_city_id for item in world.customers} <= {
        city.id for city in config.cities[:2]
    }
