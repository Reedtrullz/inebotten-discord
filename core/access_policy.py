"""Invocation permission and explicit calendar audiences are separate gates."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from core.request_context import RequestContext


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason_code: str


@dataclass(frozen=True)
class ScopeRecord:
    scope_id: str
    kind: Literal['legacy_shared', 'private_user', 'approved_group']
    owner_id: str | None = None
    collaborator_ids: frozenset[str] = frozenset()
    channel_ids: frozenset[str] = frozenset()
    read_policy: str = 'members'
    write_policy: str = 'members'

    def __post_init__(self):
        object.__setattr__(self, 'collaborator_ids', frozenset(str(value) for value in self.collaborator_ids))
        object.__setattr__(self, 'channel_ids', frozenset(str(value) for value in self.channel_ids))
        if not self.scope_id or self.kind not in ('legacy_shared', 'private_user', 'approved_group'):
            raise ValueError('Invalid calendar scope')
        if self.kind == 'private_user' and not self.scope_id.startswith('private:') or self.kind == 'approved_group' and not self.scope_id.startswith('group:'):
            raise ValueError('Named scope requires its stable kind prefix')
        if self.kind != 'legacy_shared' and not self.owner_id:
            raise ValueError('Calendar scope requires an owner ID')
        if self.kind == 'private_user':
            object.__setattr__(self, 'read_policy', 'owner')
            object.__setattr__(self, 'write_policy', 'owner')
            if self.collaborator_ids:
                raise ValueError('Private user scope has no collaborators')
        if self.kind == 'approved_group' and not self.channel_ids:
            raise ValueError('Approved group scope requires approved channels')
        if self.kind == 'legacy_shared':
            object.__setattr__(self, 'read_policy', 'invokers')
            object.__setattr__(self, 'write_policy', 'invokers')
        if self.read_policy not in ('owner', 'members', 'invokers') or self.write_policy not in ('owner', 'members', 'invokers'):
            raise ValueError('Invalid scope permission mode')

    def describe(self):
        return {'scope_id': self.scope_id, 'kind': self.kind, 'owner_id': self.owner_id,
                'collaborator_ids': sorted(self.collaborator_ids), 'channel_ids': sorted(self.channel_ids),
                'read_policy': self.read_policy, 'write_policy': self.write_policy}


class AccessPolicy:
    def __init__(self, scopes=None, *, default_scope='shared'):
        records = list(scopes) if scopes is not None else [ScopeRecord('shared', 'legacy_shared')]
        self.scopes = MappingProxyType({record.scope_id: record for record in records})
        if len(self.scopes) != len(records) or default_scope not in self.scopes:
            raise ValueError('Duplicate or missing default scope')
        self.default_scope = default_scope

    def authorize(self, actor: RequestContext | None, scope_id: str, operation: str) -> AccessDecision:
        scope = self.scopes.get(scope_id)
        if scope is None:
            return AccessDecision(False, 'unknown_scope')
        if operation not in ('read', 'write'):
            return AccessDecision(False, 'unknown_operation')
        if scope.kind == 'legacy_shared':
            # None is the existing trusted internal/background adapter. Invocation
            # allowlists and mention gates are still required for external input.
            return AccessDecision(True, 'legacy_shared_invokers')
        if actor is None or not actor.user_id:
            return AccessDecision(False, 'actor_required')
        if scope.kind == 'private_user' and actor.channel_kind not in ('dm', 'console'):
            return AccessDecision(False, 'private_audience_required')
        if scope.kind == 'approved_group' and actor.channel_id not in scope.channel_ids:
            return AccessDecision(False, 'unapproved_audience')
        permission = scope.read_policy if operation == 'read' else scope.write_policy
        if actor.user_id == scope.owner_id:
            return AccessDecision(True, 'scope_owner')
        if permission == 'members' and actor.user_id in scope.collaborator_ids:
            return AccessDecision(True, 'scope_collaborator')
        return AccessDecision(False, 'scope_membership_required')

    def describe(self):
        return [record.describe() for record in self.scopes.values()]

    @classmethod
    def from_config(cls, config):
        mode = getattr(config, 'CALENDAR_MODE', 'legacy_shared')
        owner = str(getattr(config, 'CALENDAR_OWNER_ID', '') or '')
        records = [ScopeRecord('shared', 'legacy_shared')]
        if mode == 'legacy_shared':
            return cls(records)
        if mode == 'private_user':
            selected = f'private:{owner}'
            records.append(ScopeRecord(selected, mode, owner_id=owner))
        elif mode == 'approved_group':
            selected = 'group:approved'
            channels = frozenset(str(value) for value in getattr(config, 'CALENDAR_GROUP_CHANNELS', []))
            collaborators = frozenset(str(value) for value in getattr(config, 'CALENDAR_COLLABORATORS', []))
            records.append(ScopeRecord(selected, mode, owner_id=owner, collaborator_ids=collaborators,
                                       channel_ids=channels))
        else:
            raise ValueError('Invalid CALENDAR_MODE')
        return cls(records, default_scope=selected)


def authorize(actor: RequestContext, scope_id: str, operation: str, *, policy: AccessPolicy | None = None) -> AccessDecision:
    if policy is None:
        return AccessDecision(False, 'policy_required')
    return policy.authorize(actor, scope_id, operation)


def invocation_decision(actor: RequestContext, *, mode='legacy', allowed_users=(), allowed_channels=()) -> AccessDecision:
    if mode not in ('legacy', 'allowlist'):
        return AccessDecision(False, 'invalid_invocation_mode')
    users = {str(value) for value in allowed_users}
    channels = {str(value) for value in allowed_channels}
    if (mode == 'allowlist' and not users) or (users and actor.user_id not in users):
        return AccessDecision(False, 'invocation_user_denied')
    if actor.channel_kind == 'dm':
        return AccessDecision(True, 'direct_message')
    if mode == 'legacy' and actor.channel_kind == 'group_dm':
        return AccessDecision(True, 'legacy_group_dm_bypass')
    if (mode == 'allowlist' and not channels) or (channels and actor.channel_id not in channels):
        return AccessDecision(False, 'invocation_channel_denied')
    return AccessDecision(True, 'invocation_allowed')


def invocation_description(config):
    mode = getattr(config, 'INVOCATION_MODE', 'legacy')
    return {'mode': mode, 'allowed_users': [str(value) for value in getattr(config, 'ALLOWED_USERS', [])],
            'allowed_channels': [str(value) for value in getattr(config, 'ALLOWED_CHANNELS', [])],
            'legacy_group_dm_bypass': mode == 'legacy',
            'inherited_defaults': bool(getattr(config, 'AUTHORIZATION_DEFAULTS_INHERITED', False))}


def describe_access_settings(values):
    """Show selected permissions using only nonsecret access fields."""
    from types import SimpleNamespace
    config = SimpleNamespace(CALENDAR_MODE=values.get('CALENDAR_MODE', 'legacy_shared'),
                             CALENDAR_OWNER_ID=values.get('CALENDAR_OWNER_ID', ''),
                             CALENDAR_GROUP_CHANNELS=_ids(values.get('CALENDAR_GROUP_CHANNELS', '')),
                             CALENDAR_COLLABORATORS=_ids(values.get('CALENDAR_COLLABORATORS', '')))
    try:
        policy = AccessPolicy.from_config(config)
    except ValueError:
        return 'Kalenderområdet mangler en gyldig eier eller godkjent kanal; tilgangen er ikke klar.'
    return policy_summary(policy) + ' ' + (
        'Invokasjon krever brukere i ALLOWED_USERS; grupper krever kanaler i ALLOWED_CHANNELS.'
        if values.get('INVOCATION_MODE', 'legacy') == 'allowlist' else
        'Legacy-invokasjon: tomme lister er åpne; direktemeldinger og gruppe-DM omgår kanalfilteret.')


def _ids(value):
    return [part.strip() for part in str(value or '').split(',') if part.strip()]


def policy_summary(policy):
    scope = policy.scopes[policy.default_scope]
    if scope.kind == 'legacy_shared':
        return 'Delt legacy-kalender: alle som kan invokere boten kan lese og skrive. Eksisterende data forblir delt.'
    if scope.kind == 'private_user':
        return f'Privat kalender for bruker {scope.owner_id}: bare eieren kan lese og skrive i en direktemelding. Legacy-data er ikke flyttet.'
    return (f'Godkjent gruppe: eier {scope.owner_id}; medlemmer {", ".join(sorted(scope.collaborator_ids)) or "ingen"}; '
            f'kanaler {", ".join(sorted(scope.channel_ids))}; lesing {scope.read_policy}, skriving {scope.write_policy}. '
            'Legacy-data er ikke flyttet.')
