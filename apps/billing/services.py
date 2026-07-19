from apps.core.services.ai import calculate_cost

from .models import APIUsage


def record_usage(usage: dict, *, service: str, api_type: str, model: str,
                 step: str = "", **relations):
    """Create one APIUsage record for any LLM/embedding call.

    `relations` are the APIUsage foreign keys to attach (digest=, item=,
    research=, article=). Returns the created row, or None if usage is empty.
    """
    if not usage or usage.get("total_tokens", 0) == 0:
        return None
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return APIUsage.objects.create(
        service=service,
        api_type=api_type,
        model=model,
        step=step,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=usage.get("total_tokens", 0),
        cost_usd=calculate_cost(model, prompt, completion),
        **relations,
    )


def record_digest_usage(usage: dict, *, step: str, api_type: str,
                        model: str, digest, item=None):
    """Create one APIUsage record for a digest pipeline LLM/embedding call."""
    return record_usage(usage, service=APIUsage.Service.DIGEST, api_type=api_type,
                        model=model, step=step, digest=digest, item=item)
