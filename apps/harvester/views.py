import json

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.admin import site as admin_site
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.harvester.dashboard import build_harvester_context
from apps.harvester.models import PipelineSettings, STAGE_FIELD_NAMES
from apps.harvester.services.pipeline import get_manager


@staff_member_required
def harvester_dashboard(request):
    context = {**admin_site.each_context(request), "title": "Harvester Dashboard"}
    context.update(build_harvester_context(request))
    return render(request, "admin/harvester_dashboard.html", context)


@staff_member_required
def harvester_dashboard_api(request):
    return JsonResponse(build_harvester_context(request))


@staff_member_required
@require_POST
def harvester_toggle(request):
    settings = PipelineSettings.load()
    new_state = not settings.is_active
    PipelineSettings.set_field(is_active=new_state)
    manager = get_manager()
    return JsonResponse({"active": new_state, "running": manager is not None})


@staff_member_required
@require_POST
def harvester_stage_toggle(request):
    body = json.loads(request.body)
    stage = body.get("stage")
    if stage not in STAGE_FIELD_NAMES:
        return JsonResponse({"error": "Invalid stage"}, status=400)

    settings = PipelineSettings.load()
    new_value = not getattr(settings, stage)
    PipelineSettings.set_field(**{stage: new_value})
    return JsonResponse({"stage": stage, "enabled": new_value})
