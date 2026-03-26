from apps.core.services.ai import calculate_cost

from .models import APIUsage


def record_digest_usage(usage: dict, *, step: str, api_type: str,
                        model: str, digest, item=None):
    """Create one APIUsage record for a digest pipeline LLM/embedding call."""
    if not usage or usage.get("total_tokens", 0) == 0:
        return
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    APIUsage.objects.create(
        service=APIUsage.Service.DIGEST,
        api_type=api_type,
        model=model,
        step=step,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=usage.get("total_tokens", 0),
        cost_usd=calculate_cost(model, prompt, completion),
        digest=digest,
        item=item,
    )
