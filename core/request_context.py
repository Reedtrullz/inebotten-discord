"""Immutable invocation identity and task-local request scope."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    locale: str

    @classmethod
    def from_message(cls, message, locale: str):
        guild = getattr(message, 'guild', None)
        return cls(str(getattr(message, 'id', None) or uuid4()), str(message.author.id),
                   str(message.channel.id), str(guild.id) if guild else None, locale)


_ACTIVE: ContextVar[RequestContext | None] = ContextVar('inebotten_request', default=None)


def current_request() -> RequestContext | None:
    return _ACTIVE.get()


@contextmanager
def request_scope(context: RequestContext):
    token = _ACTIVE.set(context)
    try:
        yield context
    finally:
        _ACTIVE.reset(token)


def request_localization(localization):
    context = current_request()
    if context is not None and hasattr(localization, 'for_language'):
        return localization.for_language(context.locale)
    return localization
