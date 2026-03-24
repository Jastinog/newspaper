from rest_framework import serializers

from .models import Article, Category, Feed


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "order"]


class FeedSerializer(serializers.ModelSerializer):
    article_count = serializers.IntegerField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    category_slug = serializers.CharField(source="category.slug", read_only=True, default="")

    class Meta:
        model = Feed
        fields = [
            "id", "title", "url",
            "category", "category_name", "category_slug",
            "last_fetched", "enabled", "article_count",
        ]


class ArticleListSerializer(serializers.ModelSerializer):
    feed_title = serializers.CharField(source="feed.title", read_only=True)
    category_name = serializers.CharField(source="feed.category.name", read_only=True, default="")
    category_slug = serializers.CharField(source="feed.category.slug", read_only=True, default="")

    class Meta:
        model = Article
        fields = [
            "id", "title", "url", "published",
            "read", "starred", "feed_title",
            "category_name", "category_slug",
        ]


class ArticleDetailSerializer(serializers.ModelSerializer):
    feed_title = serializers.CharField(source="feed.title", read_only=True)
    category_name = serializers.CharField(source="feed.category.name", read_only=True, default="")
    category_slug = serializers.CharField(source="feed.category.slug", read_only=True, default="")

    class Meta:
        model = Article
        fields = [
            "id", "title", "url", "content", "summary",
            "published", "read", "starred",
            "feed_title", "category_name", "category_slug", "feed",
        ]


class ArticleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ["read", "starred"]
