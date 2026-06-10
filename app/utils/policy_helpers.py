"""Policy API response helpers."""
from app.models import Policy
from app.schemas import PolicyResponse, PolicyTaxContext
from app.utils.payment_modes import payment_mode_label
from app.utils.policy_tax import policy_tax_context


def build_policy_response(policy: Policy) -> PolicyResponse:
    ctx = policy_tax_context(policy)
    base = PolicyResponse.model_validate(policy)
    base.tax_context = PolicyTaxContext(
        country_code=ctx["country_code"],
        tax_regime=ctx["tax_regime"],
        applicable_tax_types=ctx.get("applicable_tax_types") or [],
        tax_inclusive=ctx["tax_inclusive"],
        regime_label=ctx.get("regime_label"),
        currency_symbol=ctx.get("currency_symbol"),
    )
    pm = policy.payment_method.value if hasattr(policy.payment_method, "value") else policy.payment_method
    base.payment_method = pm
    base.allowed_payment_modes = policy.allowed_payment_modes
    return base
