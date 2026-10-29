from __future__ import annotations

from abc import ABC

from .logger_system import ILoggableSystem


class IToolDiscoverySystem(ILoggableSystem, ABC):
    """Declare the tool discovery System slot contract."""

    pass
