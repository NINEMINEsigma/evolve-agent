"""Post-message pure types, with no methods or runtime initialization.

These types may depend on entity.messages and entity.puretype. The pre-message
entity.puretype package and the message definition layer must not import this
package. Each phase explicitly exports its own types without a shared facade.
"""

from .session import ToolChainReplacement

__all__ = ["ToolChainReplacement"]
