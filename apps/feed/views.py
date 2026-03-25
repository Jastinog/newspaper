from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Article, Category, Feed
from .serializers import (
    ArticleDetailSerializer,
    ArticleListSerializer,
    ArticleUpdateSerializer,
    CategorySerializer,
    FeedSerializer,
)


# ── API Views ─────────────────────────────────────────────


class ArticleListAPI(generics.ListAPIView):
    serializer_class = ArticleListSerializer

    def get_queryset(self):
        qs = Article.objects.select_related("feed", "feed__category").all()
        category = self.request.query_params.get("category")
        feed = self.request.query_params.get("feed")
        is_read = self.request.query_params.get("read")
        is_starred = self.request.query_params.get("starred")

        if category:
            qs = qs.filter(feed__category__slug=category)
        if feed:
            qs = qs.filter(feed_id=feed)
        if is_read is not None:
            qs = qs.filter(read=is_read.lower() in ("true", "1"))
        if is_starred is not None:
            qs = qs.filter(starred=is_starred.lower() in ("true", "1"))
        return qs


class ArticleDetailAPI(generics.RetrieveUpdateAPIView):
    queryset = Article.objects.select_related("feed", "feed__category").all()

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return ArticleUpdateSerializer
        return ArticleDetailSerializer


class FeedListAPI(generics.ListAPIView):
    serializer_class = FeedSerializer

    def get_queryset(self):
        return Feed.objects.select_related("category").annotate(
            article_count=Count("articles"),
        ).all()


class CategoryListAPI(generics.ListAPIView):
    serializer_class = CategorySerializer
    queryset = Category.objects.all()


@api_view(["POST"])
def toggle_feed_api(request, pk):
    feed = get_object_or_404(Feed, pk=pk)
    feed.enabled = not feed.enabled
    feed.save(update_fields=["enabled"])
    return Response({"id": feed.id, "enabled": feed.enabled})
