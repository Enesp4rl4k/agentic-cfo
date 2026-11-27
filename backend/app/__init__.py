# backend/app/__init__.py
# The browser journey's API runs on a simulated date (APP_CLOCK_START, honoured only under APP_ENV test/ci and
# refused by preflight in production): installed before any app module binds `datetime`.
from app.core.clock import install_from_env as _install_clock_from_env

_install_clock_from_env()
