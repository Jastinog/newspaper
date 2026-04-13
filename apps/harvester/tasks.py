import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.harvester.models import HarvesterContent, HarvesterEmbedding, HarvesterImage, RunStatus
from apps.harvester.retention import ARTICLE_RETENTION_DAYS
from apps.harvester.services.downloader import DOWNLOAD_BATCH_SIZE
from apps.harvester.services.extractor import EXTRACT_BATCH_SIZE

logger = logging.getLogger(__name__)


@shared_task(name="harvester.harvest")
def harvest_feeds():
    """Pick eligible feeds and fetch them."""
    from apps.harvester.services.scheduler import FeedHarvester

    runs = FeedHarvester().harvest()

    total_new = sum(r.new_articles for r in runs)
    errors = sum(1 for r in runs if r.status == RunStatus.ERROR)

    logger.info(
        "Harvest done: %d feeds, %d new articles, %d errors",
        len(runs), total_new, errors,
    )
    return {
        "feeds_fetched": len(runs),
        "new_articles": total_new,
        "errors": errors,
    }


@shared_task(name="harvester.extract")
def extract_content():
    """Extract article content for a batch of unfetched articles."""
    from apps.harvester.services.extractor import ContentExtractor

    run = HarvesterContent.objects.create(status=RunStatus.SUCCESS)

    try:
        total, extracted, fallback_count, errors = ContentExtractor().extract_new(
            batch_size=EXTRACT_BATCH_SIZE,
        )
        run.articles_found = total
        run.articles_extracted = extracted
        run.articles_fallback = fallback_count
        run.articles_failed = total - extracted
        if errors:
            run.error_message = "; ".join(errors[:10])
    except Exception as e:
        run.status = RunStatus.ERROR
        run.error_message = str(e)[:2000]
        logger.exception("extract_content failed")

    run.finished_at = timezone.now()
    run.save()

    logger.info(
        "Extract done: %d found, %d extracted, %d failed",
        run.articles_found, run.articles_extracted, run.articles_failed,
    )
    return {
        "articles_found": run.articles_found,
        "articles_extracted": run.articles_extracted,
        "articles_failed": run.articles_failed,
    }


@shared_task(name="harvester.download")
def download_images():
    """Download images for a batch of pending article images."""
    from apps.harvester.services.downloader import ImageDownloader

    run = HarvesterImage.objects.create(status=RunStatus.SUCCESS)

    try:
        processed, downloaded, skipped = ImageDownloader().download_new(
            batch_size=DOWNLOAD_BATCH_SIZE,
        )
        run.images_found = processed
        run.images_downloaded = downloaded
        run.images_skipped = skipped
    except Exception as e:
        run.status = RunStatus.ERROR
        run.error_message = str(e)[:2000]
        logger.exception("download_images failed")

    run.finished_at = timezone.now()
    run.save()

    logger.info(
        "Download done: %d found, %d downloaded, %d skipped",
        run.images_found, run.images_downloaded, run.images_skipped,
    )
    return {
        "images_found": run.images_found,
        "images_downloaded": run.images_downloaded,
        "images_skipped": run.images_skipped,
    }


@shared_task(name="harvester.embed")
def embed_articles():
    """Embed unembedded articles: chunk, embed, save."""
    from apps.harvester.services.embedder import ArticleEmbedder

    run = HarvesterEmbedding.objects.create(status=RunStatus.SUCCESS)

    try:
        articles, chunks, tokens = ArticleEmbedder().embed_new()
        run.articles_found = articles
        run.articles_embedded = articles
        run.chunks_created = chunks
        run.tokens_used = tokens
    except Exception as e:
        run.status = RunStatus.ERROR
        run.error_message = str(e)[:2000]
        logger.exception("embed_articles failed")

    run.finished_at = timezone.now()
    run.save()

    logger.info(
        "Embed done: %d embedded, %d chunks, %d tokens",
        run.articles_embedded, run.chunks_created, run.tokens_used,
    )
    return {
        "articles_embedded": run.articles_embedded,
        "chunks_created": run.chunks_created,
        "tokens_used": run.tokens_used,
    }


@shared_task(name="harvester.cleanup")
def cleanup_articles():
    """Delete articles older than 14 days that are not linked to any digest."""
    from apps.feed.models import Article, ArticleImage
    from apps.harvester.services.downloader import _remove_image

    cutoff = timezone.now() - timedelta(days=ARTICLE_RETENTION_DAYS)
    article_ids = list(
        Article.objects
        .filter(published__lt=cutoff)
        .exclude(digest_items__isnull=False)
        .values_list("pk", flat=True)
    )

    images_qs = ArticleImage.objects.filter(
        article_id__in=article_ids,
    ).exclude(image="")
    deleted_images = images_qs.count()
    for img in images_qs.iterator():
        _remove_image(img)

    deleted_articles, _ = Article.objects.filter(pk__in=article_ids).delete()

    logger.info(
        "Cleanup done: %d articles, %d images deleted",
        deleted_articles, deleted_images,
    )
    return {
        "deleted_articles": deleted_articles,
        "deleted_images": deleted_images,
    }
