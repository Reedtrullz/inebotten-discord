"""Truthful, immutable results shared by dispatch and delivery layers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum


class DeliveryState(str, Enum):
    DELIVERED = "delivered"
    NOT_DELIVERED = "not_delivered"
    UNKNOWN = "unknown"


SEND_ERROR_CODES = frozenset(
    {
        "empty",
        "daily_quota",
        "forbidden",
        "http",
        "timeout",
        "transport",
        "send_task_cancelled",
        "send_task_exception",
        "partial_send",
        "missing_channel",
        "invalid_channel",
        "missing_adapter",
    }
)


@dataclass(frozen=True, slots=True)
class MessageSendResult:
    state: DeliveryState
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DeliveryState):
            raise ValueError("invalid_delivery_state")
        if self.state is DeliveryState.DELIVERED and self.error_code is not None:
            raise ValueError("delivered_with_error")
        if self.state is not DeliveryState.DELIVERED:
            if self.error_code not in SEND_ERROR_CODES:
                raise ValueError("invalid_send_error_code")


class MessageSendCancelled(asyncio.CancelledError):
    """Cancellation observed only after the owned send reaches known truth."""

    def __init__(self, result: MessageSendResult) -> None:
        self.result = result
        super().__init__(result.error_code or "message_send_cancelled")


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    ok: bool
    mutated: bool = False
    response_sent: bool = False
    retryable: bool = False
    error_code: str | None = None
    commit_unknown: bool = False
    delivery_result: MessageSendResult | None = None

    def __post_init__(self) -> None:
        if self.commit_unknown and (self.ok or self.retryable):
            raise ValueError("invalid_unknown_commit_outcome")
        if self.response_sent and self.delivery_result is None:
            raise ValueError("response_sent_without_delivery")
        if self.delivery_result is not None:
            delivered = self.delivery_result.state is DeliveryState.DELIVERED
            if self.response_sent is not delivered:
                raise ValueError("inconsistent_delivery_outcome")
            if self.delivery_result.state is DeliveryState.UNKNOWN and self.retryable:
                raise ValueError("retryable_unknown_delivery")

    @classmethod
    def success(
        cls,
        *,
        mutated: bool = False,
        response_sent: bool = False,
    ) -> "DispatchOutcome":
        return cls(
            ok=True,
            mutated=mutated,
            response_sent=response_sent,
            retryable=False,
            error_code=None,
            commit_unknown=False,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        *,
        mutated: bool = False,
        response_sent: bool = False,
        retryable: bool = False,
        commit_unknown: bool = False,
    ) -> "DispatchOutcome":
        return cls(
            ok=False,
            mutated=mutated,
            response_sent=response_sent,
            retryable=retryable,
            error_code=code,
            commit_unknown=commit_unknown,
        )

    def with_delivery(self, result: MessageSendResult) -> "DispatchOutcome":
        return replace(
            self,
            response_sent=(result.state is DeliveryState.DELIVERED),
            retryable=(self.retryable and result.state is not DeliveryState.UNKNOWN),
            delivery_result=result,
        )


class ManagerMutationError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        mutated: bool,
        commit_unknown: bool = False,
    ) -> None:
        self.code = code
        self.mutated = mutated
        self.commit_unknown = commit_unknown
        super().__init__(code)


class ManagerMutationCancelled(asyncio.CancelledError):
    def __init__(
        self,
        code: str,
        *,
        mutated: bool,
        retryable: bool,
        commit_unknown: bool = False,
    ) -> None:
        self.code = code
        self.mutated = mutated
        self.retryable = retryable
        self.commit_unknown = commit_unknown
        super().__init__(code)


class DispatchCancelled(asyncio.CancelledError):
    def __init__(
        self,
        outcome: DispatchOutcome,
        *,
        decision_route: object | None = None,
        decision_outcome: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.decision_route = decision_route
        self.decision_outcome = decision_outcome
        super().__init__(outcome.error_code or "dispatch_cancelled")


class ExternalCommitState(str, Enum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "commit_unknown"


@dataclass(frozen=True, slots=True)
class ExternalMutationResult:
    ok: bool
    state: ExternalCommitState
    value: object | None = None
    error_code: str | None = None
