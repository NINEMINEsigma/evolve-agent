"""Typed external-resource cleanup errors and structural exception splitting."""

from __future__ import annotations

from entity.puretype.resource_cleanup import CleanupWarning
from system.lifecycle import LifecycleFailure


class ResourceCleanupTimeout(TimeoutError):
    """A located cleanup phase exhausted its observation deadline."""

    def __init__(self, warning: CleanupWarning) -> None:
        self.warning = warning
        super().__init__(warning.message)


class ResourceCleanupPendingError(RuntimeError):
    """A new operation conflicts with a resource that is still being released."""


class CleanupErrorSink:
    """Collects cleanup-phase errors for one resource generation.

    The sink does not own Runtime or Application. Classification happens only
    after ``take`` returns the original exception objects.
    """

    def __init__(self) -> None:
        self._errors: list[BaseException] = []
        self._taken = False

    def submit(self, error: BaseException) -> None:
        """Record one cleanup-phase error. Identical object identity is idempotent."""
        if self._taken:
            raise LifecycleFailure("Cleanup error submitted after the cleanup generation ended")
        if any(existing is error for existing in self._errors):
            return
        self._errors.append(error)

    def take(self) -> tuple[BaseException, ...]:
        """Return and clear this generation once, preserving submission order."""
        if self._taken:
            raise LifecycleFailure("Cleanup error sink already taken")
        self._taken = True
        taken = tuple(self._errors)
        self._errors.clear()
        return taken

    def has_errors(self) -> bool:
        """Return whether this generation currently holds unsubmitted errors."""
        return bool(self._errors)


def split_cleanup_timeouts(
    error: BaseException,
) -> tuple[tuple[ResourceCleanupTimeout, ...], BaseException | None]:
    """Split explicit cleanup timeouts from every other exception.

    Nested groups keep their traceback, cause, and cancellation type. Text and
    arbitrary causes are never used to guess recoverability.
    """
    if isinstance(error, ResourceCleanupTimeout):
        return (error,), None
    if isinstance(error, BaseExceptionGroup):
        timeouts: list[ResourceCleanupTimeout] = []
        remaining: list[BaseException] = []
        for member in error.exceptions:
            member_timeouts, member_remaining = split_cleanup_timeouts(member)
            timeouts.extend(member_timeouts)
            if member_remaining is not None:
                remaining.append(member_remaining)
        if not remaining:
            return tuple(timeouts), None
        if len(remaining) == 1 and not isinstance(remaining[0], BaseExceptionGroup):
            rebuilt: BaseException = remaining[0]
        else:
            rebuilt = BaseExceptionGroup(error.message, remaining)
        return tuple(timeouts), rebuilt
    return (), error
