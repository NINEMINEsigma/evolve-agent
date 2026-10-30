"""Typed external-resource cleanup errors and structural exception splitting."""

from __future__ import annotations

from entity.error import LifecycleFailure, ResourceCleanupTimeout


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
        matched, remaining = error.split(ResourceCleanupTimeout)
        if matched is None:
            return (), error
        timeouts: list[ResourceCleanupTimeout] = []

        def collect(member: BaseException) -> None:
            if isinstance(member, ResourceCleanupTimeout):
                timeouts.append(member)
            elif isinstance(member, BaseExceptionGroup):
                for child in member.exceptions:
                    collect(child)

        collect(matched)
        return tuple(timeouts), remaining
    return (), error
