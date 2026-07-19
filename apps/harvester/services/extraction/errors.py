import requests


class ErrorClassifier:
    """Classify extraction exceptions into stable error categories."""

    TIMEOUT = "timeout"
    HTTP_403 = "http_403"
    HTTP_404 = "http_404"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    TOO_SHORT = "too_short"
    CONNECTION = "connection"
    READABILITY = "readability"
    OTHER = "other"

    @classmethod
    def classify(cls, error: Exception) -> tuple[str, str]:
        """Return (category, message) for an extraction exception."""
        msg = str(error)

        if isinstance(error, requests.exceptions.Timeout):
            return cls.TIMEOUT, msg
        if isinstance(error, requests.exceptions.ConnectionError):
            return cls.CONNECTION, msg
        if isinstance(error, requests.exceptions.HTTPError):
            code = error.response.status_code if error.response is not None else 0
            if code == 403:
                return cls.HTTP_403, f"{code} Forbidden"
            if code == 404:
                return cls.HTTP_404, f"{code} Not Found"
            if 400 <= code < 500:
                return cls.HTTP_4XX, f"{code} {msg}"
            if code >= 500:
                return cls.HTTP_5XX, f"{code} {msg}"
            return cls.OTHER, msg

        if "readability" in msg.lower() or "lxml" in msg.lower() or "parse" in msg.lower():
            return cls.READABILITY, msg

        return cls.OTHER, msg
