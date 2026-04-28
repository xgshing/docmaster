from django.conf import settings


class DesktopRefererMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("HTTP_X_DOCMASTER_DESKTOP") == "1":
            origin = self._get_origin(request)
            request.META.setdefault("HTTP_ORIGIN", origin)
            request.META.setdefault("HTTP_REFERER", f"{origin}/")
        return self.get_response(request)

    def _get_origin(self, request):
        configured_origin = settings.DOCMASTER_DESKTOP_ALLOWED_ORIGIN.rstrip("/")
        if configured_origin:
            return configured_origin
        scheme = "https" if request.is_secure() else "http"
        return f"{scheme}://{request.get_host()}"
