# abcp_tender_portal/urls.py

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include(("tender.urls", "tender"), namespace="tender")),
]

# --- Раздача static и media ---

if settings.DEBUG:
    # В режиме разработки используем стандартный helper
    from django.conf.urls.static import static

    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # На Timeweb (DEBUG = False) статические файлы и media
    # отдаём через django.views.static.serve
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
