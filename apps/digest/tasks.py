import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="digest.generate")
def generate_digest():
    """Generate daily digest for all languages."""
    from apps.digest.services import DigestService

    service = DigestService()
    digests = service.run()

    result = []
    for d in digests:
        sections = d.sections.count()
        logger.info("Digest [%s] %s: %d sections", d.language, d.date, sections)
        result.append({"language": d.language, "date": str(d.date), "sections": sections})
    return result
