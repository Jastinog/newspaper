from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/digest/", consumers.DigestConsumer.as_asgi()),
]
