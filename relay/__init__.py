"""RELAY - stable daedalus<->venus bridges + the constant fleet stream."""

from .bridge import Relay, watch
from . import content

__all__ = ["Relay", "watch", "content", "content_VERSION"]
content_VERSION = content.VERSION
