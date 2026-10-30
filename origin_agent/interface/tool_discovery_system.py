from __future__ import annotations

from abc import ABC

from .runtime_system import IDPRuntimeSystem


class IToolDiscoverySystem(IDPRuntimeSystem, ABC):
    """Declare the tool discovery System slot contract."""

    pass
