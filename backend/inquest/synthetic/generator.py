import math
from dataclasses import dataclass
from datetime import UTC, timedelta
from random import Random
from zoneinfo import ZoneInfo

from inquest.synthetic.models import (
    Channel,
    Customer,
    Device,
    Flow,
    GeneratorConfig,
    Merchant,
    Payment,
    Scenario,
    Transaction,
    Truth,
    World,
)

GENERATOR_VERSION = 1
SCENARIO_LENGTHS: dict[Scenario, tuple[int, int]] = {
    "account_takeover": (2, 5),
    "card_testing": (3, 8),
    "velocity_burst": (3, 6),
    "impossible_travel": (2, 2),
    "new_device_high_value": (1, 2),
    "mule_cash_out": (3, 7),
    "merchant_collusion": (3, 6),
    "upi_collect_scam": (2, 4),
    "upi_sim_swap": (2, 4),
}


@dataclass(frozen=True)
class Profile:
    customer: Customer
    device: Device
    amount_scale: float
    activity: float
    upi_share: float
    preferred_merchants: tuple[Merchant, ...]


@dataclass(frozen=True)
class Attempt:
    payment: Payment
    is_fraud: bool = False
    scenario: Scenario | None = None
    episode_id: str | None = None


class Generator:
    def __init__(self, config: GeneratorConfig) -> None:
        self.config = config
        self.routine_rng = Random(f"{config.seed}:routine")
        self.episode_rng = Random(f"{config.seed}:episodes")
        self.timezone = ZoneInfo(config.timezone)
        self.distributions = {item.category: item for item in config.amounts}
        self.merchants = self._merchants()
        self.profiles = self._profiles()

    def _merchants(self) -> tuple[Merchant, ...]:
        rng = self.routine_rng
        result = []
        for index in range(self.config.merchant_count):
            category = self.config.amounts[index % len(self.config.amounts)].category
            result.append(
                Merchant(
                    id=f"merchant-{index + 1:04d}",
                    alias=f"{category.replace('_', ' ').title()} {index + 1:04d}",
                    category=category,
                    city_id=rng.choice(self.config.cities).id,
                    risk_tier="elevated" if rng.random() < 0.12 else "standard",
                )
            )
        return tuple(result)

    def _profiles(self) -> tuple[Profile, ...]:
        rng = self.routine_rng
        profiles = []
        for index in range(self.config.customer_count):
            key = f"{index + 1:05d}"
            city = rng.choice(self.config.cities)
            pool = [merchant for merchant in self.merchants if merchant.city_id == city.id]
            preferred = rng.sample(pool or self.merchants, k=min(len(pool or self.merchants), 5))
            profiles.append(
                Profile(
                    customer=Customer(
                        id=f"customer-{key}", alias=f"Customer {key}", home_city_id=city.id
                    ),
                    device=Device(id=f"device-{key}"),
                    amount_scale=rng.lognormvariate(0, 0.55),
                    activity=rng.uniform(0.5, 1.5),
                    upi_share=rng.uniform(0.3, 0.85),
                    preferred_merchants=tuple(preferred),
                )
            )
        return tuple(profiles)

    def _amount(self, rng: Random, merchant: Merchant, profile: Profile, scale: float = 1) -> int:
        distribution = self.distributions[merchant.category]
        median = distribution.median_minor * profile.amount_scale * scale
        sampled = rng.lognormvariate(math.log(median), distribution.log_sigma)
        return max(1, round(sampled))

    def _routine(self) -> list[Attempt]:
        rng = self.routine_rng
        attempts = []
        weights = [self.distributions[merchant.category].weight for merchant in self.merchants]
        for profile in self.profiles:
            mean = self.config.days * self.config.attempts_per_customer_week * profile.activity / 7
            count = max(1, round(rng.gauss(mean, math.sqrt(mean))))
            for _ in range(count):
                day = rng.randrange(self.config.days)
                if rng.random() < 0.06:
                    day = min(self.config.days - 1, (day // 30) * 30 + rng.randrange(3))
                occurred_at = self.config.start + timedelta(days=day, seconds=rng.randrange(86400))
                if rng.random() < 0.75:
                    local_hour = occurred_at.astimezone(self.timezone).hour
                    if local_hour < 7 or local_hour >= 21:
                        local_time = occurred_at.astimezone(self.timezone).replace(
                            hour=rng.randrange(7, 21)
                        )
                        shifted = local_time.astimezone(UTC)
                        if (
                            self.config.start
                            <= shifted
                            < self.config.start + timedelta(days=self.config.days)
                        ):
                            occurred_at = shifted
                merchant = (
                    rng.choice(profile.preferred_merchants)
                    if rng.random() < 0.65
                    else rng.choices(self.merchants, weights=weights, k=1)[0]
                )
                channel: Channel = (
                    "upi"
                    if merchant.category in {"transfer", "cash_like"}
                    or rng.random() < profile.upi_share
                    else "card"
                )
                flow: Flow = "purchase" if channel == "card" else "push"
                if channel == "upi" and rng.random() < 0.1:
                    flow = "collect"
                physical_chance = 0.8 if merchant.city_id == profile.customer.home_city_id else 0.12
                city = merchant.city_id if rng.random() < physical_chance else None
                attempts.append(
                    Attempt(
                        Payment(
                            customer_id=profile.customer.id,
                            merchant_id=merchant.id,
                            device_id=profile.device.id,
                            instrument_id=f"{profile.customer.id}-{channel}",
                            city_id=city,
                            location_source="physical" if city else "remote",
                            occurred_at=occurred_at,
                            amount_minor=self._amount(rng, merchant, profile),
                            currency=self.config.currency,
                            channel=channel,
                            flow=flow,
                            declined=rng.random() < 0.035,
                            recent_reregistration=channel == "upi" and rng.random() < 0.015,
                        )
                    )
                )
        return attempts

    def _episode(
        self, scenario: Scenario, number: int, length: int, *, fraudulent: bool
    ) -> list[Attempt]:
        rng = self.episode_rng
        episode_id = f"episode-{number:05d}"
        start = self.config.start + timedelta(
            days=rng.randrange(2, self.config.days - 2), hours=rng.randrange(24)
        )
        profile = rng.choice(self.profiles)
        home = profile.customer.home_city_id
        away = rng.choice([city.id for city in self.config.cities if city.id != home])
        special = {
            "mule_cash_out": {"transfer", "cash_like"},
            "upi_collect_scam": {"retail", "utilities", "transfer"},
            "upi_sim_swap": {"transfer", "cash_like"},
        }
        categories = special.get(scenario, set(self.distributions) - {"transfer", "cash_like"})
        merchant_pool = [merchant for merchant in self.merchants if merchant.category in categories]
        fixed_merchant = rng.choice(merchant_pool)
        familiar = [
            merchant for merchant in profile.preferred_merchants if merchant in merchant_pool
        ]
        if scenario == "upi_collect_scam" and not fraudulent and familiar and rng.random() < 0.7:
            fixed_merchant = rng.choice(familiar)
        novel_device = f"device-{episode_id}"
        repeated_amount = self._amount(rng, fixed_merchant, profile)
        attempts = []
        elapsed = timedelta()

        for index in range(length):
            channel: Channel = "upi" if scenario in special else "card"
            if scenario in {"account_takeover", "velocity_burst", "new_device_high_value"}:
                channel = "upi" if rng.random() < profile.upi_share else "card"
            flow: Flow = "purchase" if channel == "card" else "push"
            if scenario == "upi_collect_scam":
                flow = "collect"
            merchant = fixed_merchant
            if scenario in {"velocity_burst", "account_takeover", "impossible_travel"}:
                merchant = rng.choice(merchant_pool)
            if (
                scenario == "account_takeover"
                and not fraudulent
                and familiar
                and rng.random() < 0.7
            ):
                merchant = rng.choice(familiar)
            if scenario in {"mule_cash_out", "merchant_collusion", "card_testing"} and index > 0:
                profile = rng.choice(self.profiles)
            city: str | None = profile.customer.home_city_id
            device = profile.device.id
            amount = self._amount(rng, merchant, profile)
            if index:
                elapsed += timedelta(seconds=rng.randint(20, 50))
                if scenario == "upi_sim_swap" and not fraudulent:
                    elapsed += timedelta(minutes=rng.randint(0, 40))
            decline_chance = 0.06
            if scenario == "card_testing":
                device = novel_device
                amount = self._amount(rng, merchant, profile, scale=rng.uniform(0.03, 0.16))
                decline_chance = 0.45 if fraudulent else 0.3
            if scenario in {"account_takeover", "new_device_high_value", "upi_sim_swap"}:
                device = novel_device
                amount = self._amount(rng, merchant, profile, scale=rng.uniform(2.0, 5.0))
                if scenario == "new_device_high_value" and rng.random() < 0.35:
                    city = away
            if scenario == "merchant_collusion":
                device = novel_device if fraudulent or rng.random() < 0.6 else device
                amount = repeated_amount if rng.random() < 0.85 else amount
            if scenario == "impossible_travel":
                city = away if index else home
                if index:
                    elapsed = timedelta(
                        minutes=rng.randint(15, 80) if fraudulent else rng.randint(55, 720)
                    )
            if scenario in special and rng.random() < 0.65:
                city = None
            is_fraud = fraudulent and (scenario != "impossible_travel" or index > 0)
            attempts.append(
                Attempt(
                    payment=Payment(
                        customer_id=profile.customer.id,
                        merchant_id=merchant.id,
                        device_id=device,
                        instrument_id=f"{profile.customer.id}-{channel}",
                        city_id=city,
                        location_source="physical" if city else "remote",
                        occurred_at=start + elapsed,
                        amount_minor=amount,
                        currency=self.config.currency,
                        channel=channel,
                        flow=flow,
                        declined=rng.random() < decline_chance,
                        recent_reregistration=scenario == "upi_sim_swap",
                    ),
                    is_fraud=is_fraud,
                    scenario=scenario,
                    episode_id=episode_id,
                )
            )
        return attempts

    def generate(self) -> World:
        attempts = self._routine()
        remaining_fraud = max(
            1, round(len(attempts) * self.config.fraud_rate / (1 - self.config.fraud_rate))
        )
        episode_number = 0
        while remaining_fraud:
            scenarios = list(SCENARIO_LENGTHS)
            self.episode_rng.shuffle(scenarios)
            for scenario in scenarios:
                if remaining_fraud == 0:
                    break
                low, high = SCENARIO_LENGTHS[scenario]
                context_count = int(scenario == "impossible_travel")
                high = min(high, remaining_fraud + context_count)
                if high < low:
                    continue
                count = self.episode_rng.randint(low, high)
                fraud_count = count - context_count
                episode_number += 1
                attempts.extend(self._episode(scenario, episode_number, count, fraudulent=True))
                remaining_fraud -= fraud_count
                for _ in range(self.config.lookalikes_per_fraud_episode):
                    episode_number += 1
                    attempts.extend(
                        self._episode(scenario, episode_number, count, fraudulent=False)
                    )

        attempts.sort(key=lambda attempt: attempt.payment.occurred_at)
        transactions = []
        truth = []
        device_ids = {profile.device.id for profile in self.profiles}
        for sequence, attempt in enumerate(attempts, 1):
            payment = attempt.payment
            transactions.append(Transaction(source_sequence=sequence, **payment.model_dump()))
            truth.append(
                Truth(
                    source_sequence=sequence,
                    is_fraud=attempt.is_fraud,
                    scenario=attempt.scenario,
                    episode_id=attempt.episode_id,
                )
            )
            device_ids.add(payment.device_id)
        return World(
            config=self.config,
            customers=tuple(profile.customer for profile in self.profiles),
            merchants=self.merchants,
            devices=tuple(Device(id=device_id) for device_id in sorted(device_ids)),
            transactions=tuple(transactions),
            truth=tuple(truth),
        )


def generate(config: GeneratorConfig) -> World:
    return Generator(config).generate()
