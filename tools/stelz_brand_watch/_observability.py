"""Optional Sentry init shared by Python workers.

Call `init_sentry(service_name)` once at program start. If SENTRY_DSN is
not set, this is a silent no-op so local dev / scripts don't crash.

Set these env vars in Railway / Vercel:
    SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
    SENTRY_ENV=production|staging|dev   (default: production)
    SENTRY_RELEASE=<commit-sha-or-tag>   (optional but recommended)

Sentry pricing: 5k events/month free which is plenty for our worker scale.
"""

import os


def init_sentry(service_name: str = "spot-the-brand") -> bool:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENV", "production"),
        release=os.getenv("SENTRY_RELEASE"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
        attach_stacktrace=True,
        max_breadcrumbs=50,
    )
    sentry_sdk.set_tag("service", service_name)
    return True


def capture_exception(exc=None):
    """Safe to call even when Sentry isn't configured."""
    try:
        import sentry_sdk
        if exc is None:
            sentry_sdk.capture_exception()
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass
