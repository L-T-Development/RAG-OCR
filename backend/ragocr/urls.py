"""
URL configuration for ragocr project.

- /admin/  → Django admin
- /api/*   → backend API (from process.urls)
- /static/ → Django static files
- /assets/, /, /<spa-route>  → React SPA from frontend/dist/ (standalone build)

In Vite dev mode the SPA paths are unused — Vite serves the frontend on its
own port and proxies /api to Django. The catch-all here only fires for the
packaged standalone build where Django serves both.
"""
from pathlib import Path

from django.contrib import admin
from django.urls import path, re_path, include
from django.http import FileResponse, HttpResponseNotFound
from django.conf import settings


def _serve_spa(request, asset_path=""):
    """Serve files from frontend/dist/. Falls back to index.html for SPA routes."""
    dist = Path(settings.FRONTEND_DIST_DIR)
    if not dist.is_dir():
        return HttpResponseNotFound("Frontend not built. Run `npm run build` in frontend/.")

    if asset_path:
        candidate = (dist / asset_path).resolve()
        # Guard against path traversal
        try:
            candidate.relative_to(dist)
        except ValueError:
            return HttpResponseNotFound()
        if candidate.is_file():
            return FileResponse(open(candidate, "rb"))

    index = dist / "index.html"
    if index.is_file():
        return FileResponse(open(index, "rb"), content_type="text/html")
    return HttpResponseNotFound("index.html not found")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('process.urls')),  # /api/...

    # SPA root + any non-API path falls back to index.html (React Router handles client-side)
    path('', _serve_spa, name='spa_root'),
    re_path(r'^(?P<asset_path>(?!api/|admin/|static/|media/).*)$', _serve_spa, name='spa_catchall'),
]
