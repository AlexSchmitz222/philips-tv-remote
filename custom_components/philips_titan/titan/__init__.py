"""Async client for Philips TVs running Titan OS (JointSpace API v6)."""

from .client import (
    TitanAuthError,
    TitanConnectionError,
    TitanCooldownError,
    TitanError,
    TitanTV,
    TitanUnreachableError,
    TitanUnsafeRequestError,
)
from .models import AmbilightState, AmbilightStyle, Volume, STYLES, STYLES_BY_KEY, KEYS
from .pairing import PairingSession, pair_request, pair_grant

__all__ = [
    "TitanTV",
    "TitanError",
    "TitanAuthError",
    "TitanConnectionError",
    "TitanCooldownError",
    "TitanUnsafeRequestError",
    "TitanUnreachableError",
    "PairingSession",
    "pair_request",
    "pair_grant",
    "AmbilightState",
    "AmbilightStyle",
    "Volume",
    "STYLES",
    "STYLES_BY_KEY",
    "KEYS",
]
