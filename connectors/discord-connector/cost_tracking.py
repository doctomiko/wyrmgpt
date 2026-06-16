from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import threading
from typing import Any, Dict, Optional

from callie_logging import setup_logging

log, _log_settings = setup_logging("cost_tracking")


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float = 0.0
    output_per_1m: float = 0.0


@dataclass(frozen=True)
class CostTelemetryConfig:
    enabled: bool = True
    monthly_budget_usd: float = 0.0
    month_to_date_start_usd: float = 0.0
    default_input_per_1m: float = 0.0
    default_output_per_1m: float = 0.0
    model_pricing_json: str = ""


@dataclass(frozen=True)
class UsageCost:
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    estimated_cost_usd: Optional[float]
    pricing_source: str
    connector_month_to_date_usd: float
    effective_month_to_date_usd: float
    monthly_budget_usd: float


_lock = threading.Lock()
_month_key = ""
_connector_month_to_date_usd = 0.0


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def extract_usage(data: Dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None, None, None
    input_tokens = _as_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _as_int(usage.get("output_tokens") or usage.get("completion_tokens"))
    total_tokens = _as_int(usage.get("total_tokens"))
    if total_tokens is None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0) if input_tokens is not None or output_tokens is not None else None
    return input_tokens, output_tokens, total_tokens


def _pricing_for_model(model: str, cfg: CostTelemetryConfig) -> tuple[ModelPricing, str]:
    model = (model or "").strip()
    raw_pricing = cfg.model_pricing_json.strip()
    if raw_pricing:
        try:
            if raw_pricing.startswith("{"):
                parsed = json.loads(raw_pricing)
                source_label = "inline_json"
            else:
                with open(os.path.expanduser(raw_pricing), "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                source_label = raw_pricing
            if isinstance(parsed, dict):
                entry = parsed.get(model)
                if isinstance(entry, dict):
                    return (
                        ModelPricing(
                            input_per_1m=_as_float(
                                entry.get("input_per_1m")
                                or entry.get("input")
                                or entry.get("input_cost_per_million")
                            ),
                            output_per_1m=_as_float(
                                entry.get("output_per_1m")
                                or entry.get("output")
                                or entry.get("output_cost_per_million")
                            ),
                        ),
                        f"{source_label}:{model}",
                    )
        except Exception as e:
            log.warning("Cost telemetry pricing JSON load failed: %s", type(e).__name__)
    return (
        ModelPricing(
            input_per_1m=cfg.default_input_per_1m,
            output_per_1m=cfg.default_output_per_1m,
        ),
        "default",
    )


def calculate_usage_cost(data: Dict[str, Any], model: str, cfg: CostTelemetryConfig) -> UsageCost:
    global _month_key, _connector_month_to_date_usd

    input_tokens, output_tokens, total_tokens = extract_usage(data)
    pricing, pricing_source = _pricing_for_model(model, cfg)
    estimated: Optional[float] = None
    if input_tokens is not None and output_tokens is not None and (pricing.input_per_1m > 0 or pricing.output_per_1m > 0):
        estimated = ((input_tokens / 1_000_000.0) * pricing.input_per_1m) + (
            (output_tokens / 1_000_000.0) * pricing.output_per_1m
        )

    with _lock:
        month_key = _current_month_key()
        if _month_key != month_key:
            _month_key = month_key
            _connector_month_to_date_usd = 0.0
        if estimated is not None:
            _connector_month_to_date_usd += estimated
        connector_mtd = _connector_month_to_date_usd

    effective_mtd = max(0.0, cfg.month_to_date_start_usd) + connector_mtd
    return UsageCost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated,
        pricing_source=pricing_source,
        connector_month_to_date_usd=connector_mtd,
        effective_month_to_date_usd=effective_mtd,
        monthly_budget_usd=max(0.0, cfg.monthly_budget_usd),
    )


def format_cost_log(cost: UsageCost) -> str:
    if cost.estimated_cost_usd is None:
        cost_part = "cost_estimate=unknown"
    else:
        cost_part = f"cost_estimate_usd={cost.estimated_cost_usd:.6f}"

    if cost.monthly_budget_usd > 0:
        pct = (cost.effective_month_to_date_usd / cost.monthly_budget_usd) * 100.0
        budget_part = (
            f"monthly_budget_usd={cost.monthly_budget_usd:.2f} "
            f"month_to_date_est_usd={cost.effective_month_to_date_usd:.4f} "
            f"budget_used_pct={pct:.1f}"
        )
    else:
        budget_part = (
            "monthly_budget_usd=unknown "
            f"connector_month_to_date_est_usd={cost.connector_month_to_date_usd:.4f}"
        )

    return (
        f"usage input_tokens={cost.input_tokens if cost.input_tokens is not None else 'unknown'} "
        f"output_tokens={cost.output_tokens if cost.output_tokens is not None else 'unknown'} "
        f"total_tokens={cost.total_tokens if cost.total_tokens is not None else 'unknown'} "
        f"{cost_part} pricing_source={cost.pricing_source} {budget_part}"
    )


def usage_cost_to_dict(cost: UsageCost) -> Dict[str, Any]:
    budget_used_pct: Optional[float] = None
    if cost.monthly_budget_usd > 0:
        budget_used_pct = (cost.effective_month_to_date_usd / cost.monthly_budget_usd) * 100.0
    return {
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "total_tokens": cost.total_tokens,
        "estimated_cost_usd": cost.estimated_cost_usd,
        "pricing_source": cost.pricing_source,
        "connector_month_to_date_usd": cost.connector_month_to_date_usd,
        "effective_month_to_date_usd": cost.effective_month_to_date_usd,
        "monthly_budget_usd": cost.monthly_budget_usd,
        "budget_used_pct": budget_used_pct,
    }
