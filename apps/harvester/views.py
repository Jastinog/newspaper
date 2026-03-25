from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.admin import site as admin_site
from django.http import JsonResponse
from django.shortcuts import render

from apps.harvester.dashboard import build_harvester_context


@staff_member_required
def harvester_dashboard(request):
    context = {**admin_site.each_context(request), "title": "Harvester Dashboard"}
    context.update(build_harvester_context(request))
    return render(request, "admin/harvester_dashboard.html", context)


@staff_member_required
def harvester_dashboard_api(request):
    return JsonResponse(build_harvester_context(request))
