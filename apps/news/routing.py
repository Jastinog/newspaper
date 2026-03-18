from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/deep-dive/<int:item_id>/", consumers.DeepDiveConsumer.as_asgi()),
]
