from django.conf import settings


def integration_status():
    return {
        "onlyoffice": {
            "configured": bool(settings.DOCMASTER_ONLYOFFICE_URL),
            "url": settings.DOCMASTER_ONLYOFFICE_URL,
        },
        "cos": {
            "configured": bool(settings.DOCMASTER_COS_BUCKET and settings.DOCMASTER_COS_REGION),
            "bucket": settings.DOCMASTER_COS_BUCKET,
            "region": settings.DOCMASTER_COS_REGION,
        },
        "database": {
            "engine": settings.DATABASES["default"]["ENGINE"],
            "name": settings.DATABASES["default"]["NAME"],
        },
    }
