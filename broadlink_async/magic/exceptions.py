"""Exceptions raised by the BroadLink Magic SDK."""


class BroadLinkMagicError(Exception):
    """Base BroadLink Magic error."""


class ImportDataError(BroadLinkMagicError):
    """Invalid Magic Home family import data."""


class DiscoveryError(BroadLinkMagicError):
    """RM Max discovery failed."""


class ProtocolError(BroadLinkMagicError):
    """Invalid or unsupported protocol data."""


class CommandError(BroadLinkMagicError):
    """Invalid remote command."""
