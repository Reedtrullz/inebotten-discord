"""Process-local proof of a committed, authorized calendar source."""
from dataclasses import dataclass
import copy
import hashlib
import hmac
import json
import secrets

from cal_system.mutation_preview import actor_key


@dataclass(frozen=True)
class DomainReceipt:
    scope_id: str
    item_id: str
    trigger_kind: str
    source_digest: str
    revision: int
    actor: tuple
    proof: str


def source_digest(item):
    return hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _proof(manager, value):
    if not hasattr(manager,'_workflow_receipt_key'):
        manager._workflow_receipt_key=secrets.token_bytes(32)
    payload=[value.scope_id,value.item_id,value.trigger_kind,value.source_digest,value.revision,list(value.actor)]
    return hmac.new(manager._workflow_receipt_key,json.dumps(payload).encode(),hashlib.sha256).hexdigest()


def source_item(manager, actor, scope_id, item_id, trigger_kind):
    if trigger_kind not in ('event_confirmed','task_due'):raise ValueError('unsupported_trigger')
    actor_key(actor)
    if not manager.access_policy.authorize(actor,scope_id,'read').allowed:raise PermissionError('scope_read_required')
    # Publication reads the committed snapshot, never an uncommitted draft.
    items=manager._storage.snapshot.get(scope_id,[])
    found=[item for item in items if item.get('id')==item_id]
    if len(found)!=1:raise ValueError('source_missing')
    item=copy.deepcopy(found[0])
    if item.get('series') or item.get('recurrence'):raise ValueError('single_item_source_required')
    if item.get('completed') or item.get('_mutation_deleted') or item.get('delete_pending') or item.get('_recurrence_readonly'):
        raise ValueError('source_inactive')
    from cal_system.event_schema import EventTime
    time=EventTime.from_item(item).validate_local()
    if trigger_kind=='event_confirmed' and time.kind!='event':raise ValueError('event_required')
    if trigger_kind=='task_due' and (time.kind!='task' or time.local_date>manager.clock.now(time.timezone).date()):
        raise ValueError('due_task_required')
    return item


def publish(manager, actor, scope_id, item_id, trigger_kind):
    with manager._storage.transaction(write=False):
        if manager._storage._async_active:raise ValueError('source_busy')
        item=source_item(manager,actor,scope_id,item_id,trigger_kind)
        value=DomainReceipt(scope_id,item_id,trigger_kind,source_digest(item),manager._storage.revision,tuple(actor_key(actor)),'')
        return DomainReceipt(**{**value.__dict__,'proof':_proof(manager,value)})


def validate(manager, actor, receipt):
    if type(receipt) is not DomainReceipt:raise ValueError('trusted_receipt_required')
    if tuple(actor_key(actor))!=receipt.actor or not hmac.compare_digest(_proof(manager,receipt),receipt.proof):
        raise PermissionError('receipt_actor_or_proof')
    item=source_item(manager,actor,receipt.scope_id,receipt.item_id,receipt.trigger_kind)
    if source_digest(item)!=receipt.source_digest or receipt.revision!=manager._storage.revision:
        raise ValueError('source_changed')
    return item
