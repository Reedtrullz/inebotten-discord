"""Allowlisted, explicitly approved local drafts; no arbitrary executors."""
from dataclasses import dataclass,asdict
import copy
import hashlib
import json
import uuid

from cal_system.mutation_preview import PreviewCache,actor_key
from cal_system.workflow_receipts import source_item,source_digest,validate as validate_receipt
from utils.storage_contract import writable_store

from core.command_registry import WORKFLOW_TEMPLATES
TEMPLATES={key:value[0] for key,value in WORKFLOW_TEMPLATES.items()}
MAX_RECIPES=16
MAX_EXECUTIONS=128


@dataclass(frozen=True)
class WorkflowRecipe:
    recipe_id: str
    owner_id: str
    scope_id: str
    trigger_kind: str
    template_id: str
    enabled: bool
    action_budget: int


def validate_workflows(recipes, owner_id):
    try:
        if not isinstance(recipes,dict) or len(recipes)>MAX_RECIPES:return False
        for key,value in recipes.items():
            if not isinstance(value,dict):return False
            recipe=WorkflowRecipe(**{field:value[field] for field in WorkflowRecipe.__dataclass_fields__})
            if (recipe.recipe_id!=key or len(key)!=32 or recipe.owner_id!=owner_id
                or recipe.template_id not in TEMPLATES or TEMPLATES[recipe.template_id]!=recipe.trigger_kind
                or type(recipe.enabled) is not bool or not isinstance(recipe.scope_id,str) or not recipe.scope_id
                or type(recipe.action_budget) is not int or not 1<=recipe.action_budget<=MAX_EXECUTIONS
                or type(value.get('used')) is not int or not 0<=value['used']<=recipe.action_budget
                or not isinstance(value.get('channel_id'),str) or not value['channel_id']
                or not isinstance(value.get('executions'),dict) or len(value['executions'])!=value['used']):return False
            for execution_id,execution in value['executions'].items():
                if (not isinstance(execution,dict) or execution.get('execution_id')!=execution_id
                    or not isinstance(execution.get('source'),dict) or len(execution.get('effects',[]))!=1
                    or execution.get('delivery_status')!='not_requested'):return False
                source=execution['source']
                if set(source)!={'item_id','trigger_kind','digest'} or source['trigger_kind']!=recipe.trigger_kind:return False
                if any(not isinstance(v,str) or not v or len(v)>128 for v in source.values()):return False
                effect=execution['effects'][0]
                expected='task_draft' if recipe.template_id=='prep_task' else 'digest_card'
                if effect.get('kind')!=expected or not isinstance(effect.get('title'),str) or len(effect['title'])>300:return False
        return True
    except (KeyError,TypeError,ValueError,AttributeError):return False


class WorkflowManager:
    def __init__(self, calendar, memory):
        self.calendar,self.memory=calendar,memory
        self._storage=memory._storage
        self.previews=PreviewCache(calendar.clock,max_items=1,max_bytes=512*1024)

    def _authorize(self,actor,scope):
        actor_key(actor)
        for op in ('read','write'):
            if not self.calendar.access_policy.authorize(actor,scope,op).allowed:raise PermissionError('workflow_scope_required')

    def _recipes(self,actor):
        return self.memory.memory.get(actor.user_id,{}).get('workflow_recipes',{})

    def _recipe(self,actor,recipe_id):
        actor_key(actor)
        recipe=self._recipes(actor).get(recipe_id)
        if recipe is None:raise PermissionError('workflow_owner_required')
        self._authorize(actor,recipe['scope_id'])
        if recipe['owner_id']!=actor.user_id or recipe['channel_id']!=actor.channel_id:raise PermissionError('workflow_audience_required')
        return recipe

    @writable_store
    async def create_recipe(self,actor,scope,template_id,*,action_budget=10):
        self._authorize(actor,scope)
        if template_id not in TEMPLATES or type(action_budget) is not int or not 1<=action_budget<=MAX_EXECUTIONS:
            raise ValueError('allowlisted_template_required')
        user=self.memory.memory.setdefault(actor.user_id,{})
        recipes=user.setdefault('workflow_recipes',{})
        if len(recipes)>=MAX_RECIPES:raise ValueError('recipe_capacity')
        recipe=asdict(WorkflowRecipe(uuid.uuid4().hex,actor.user_id,scope,TEMPLATES[template_id],template_id,False,action_budget))
        recipe.update(channel_id=actor.channel_id,used=0,executions={})
        recipes[recipe['recipe_id']]=recipe
        await self.memory._save_memory()
        return copy.deepcopy(recipe)

    @writable_store
    async def set_enabled(self,actor,recipe_id,enabled):
        if type(enabled) is not bool:raise ValueError('invalid_enabled')
        recipe=self._recipe(actor,recipe_id)
        recipe['enabled']=enabled
        await self.memory._save_memory()
        return enabled

    def list_recipes(self,actor):
        with self._storage.transaction(write=False):
            result=[]
            for recipe in self._recipes(actor).values():
                try:self._recipe(actor,recipe['recipe_id'])
                except PermissionError:continue
                result.append({key:copy.deepcopy(value) for key,value in recipe.items() if key!='executions'})
            return result

    def history(self,actor,recipe_id):
        with self._storage.transaction(write=False):
            return copy.deepcopy(list(self._recipe(actor,recipe_id)['executions'].values()))

    @staticmethod
    def _identity(recipe,receipt):
        source={'item_id':receipt.item_id,'trigger_kind':receipt.trigger_kind,'digest':receipt.source_digest}
        key=hashlib.sha256(json.dumps([recipe['recipe_id'],receipt.item_id,receipt.trigger_kind],sort_keys=True).encode()).hexdigest()
        return key,source

    def preview_recipe(self,actor,recipe_id,trigger_receipt):
        with self.calendar._storage.transaction(write=False),self._storage.transaction(write=False):
            if self.calendar._storage._async_active or self._storage._async_active:raise ValueError('store_busy')
            recipe=self._recipe(actor,recipe_id)
            if not recipe['enabled']:raise ValueError('recipe_disabled')
            item=validate_receipt(self.calendar,actor,trigger_receipt)
            if trigger_receipt.scope_id!=recipe['scope_id'] or trigger_receipt.trigger_kind!=recipe['trigger_kind']:
                raise ValueError('trigger_mismatch')
            execution_id,source=self._identity(recipe,trigger_receipt)
            old=recipe['executions'].get(execution_id)
            if old is None and recipe['used']>=recipe['action_budget']:raise ValueError('recipe_budget_exhausted')
            effect={'kind':'task_draft' if recipe['template_id']=='prep_task' else 'digest_card',
                'title':('Forbered: ' if recipe['template_id']=='prep_task' else 'Forfalt: ')+item['title'][:250],
                'date':item['date'],'source_item_id':item['id']}
            if old is not None:effect=copy.deepcopy(old['effects'][0])
            before={'id':recipe_id,'title':recipe['template_id'],'recipe':copy.deepcopy(recipe),'calendar_revision':self.calendar._storage.revision}
            after={**before,'execution_id':execution_id,'source':source,'effect':effect}
            return self.previews.create(actor,recipe['scope_id'],self._storage.revision,'recipe',[before],[after])

    async def execute_confirmed(self,actor,preview_token):
        async with self.calendar._storage.async_transaction(), self._storage.async_transaction():
            entry=self.previews.get(actor,preview_token)
            before,after=entry['before'][0],entry['after'][0]
            recipe=self._recipe(actor,before['id'])
            if not recipe['enabled']:raise ValueError('recipe_disabled')
            source=after['source']
            item=source_item(self.calendar,actor,recipe['scope_id'],source['item_id'],source['trigger_kind'])
            if source_digest(item)!=source['digest']:raise ValueError('source_changed')
            old=recipe['executions'].get(after['execution_id'])
            if old is not None:return copy.deepcopy(old)
            if entry['revision']!=self._storage.revision or recipe!=before['recipe'] or before['calendar_revision']!=self.calendar._storage.revision:
                raise ValueError('revision_changed')
            if recipe['used']>=recipe['action_budget']:raise ValueError('recipe_budget_exhausted')
            result={'execution_id':after['execution_id'],'effects':[copy.deepcopy(after['effect'])],
                'source':copy.deepcopy(source),'delivery_status':'not_requested','created_at':self.calendar.clock.now().isoformat()}
            recipe['executions'][result['execution_id']]=result;recipe['used']+=1
            await self.memory._save_memory()
            # Keep the bounded token until TTL so immediate retries get the same
            # committed receipt. Restart uses a fresh preview of the same source.
            return copy.deepcopy(result)

    def digest_card(self,actor,scope):
        if actor is None:return ''
        with self.calendar._storage.transaction(write=False),self._storage.transaction(write=False):
            if self.calendar._storage._async_active or self._storage._async_active:return ''
            titles=[]
            for recipe in self._recipes(actor).values():
                try:self._recipe(actor,recipe['recipe_id'])
                except PermissionError:continue
                if not recipe['enabled'] or recipe['scope_id']!=scope or recipe['template_id']!='due_digest':continue
                for result in recipe['executions'].values():
                    source=result['source']
                    try:item=source_item(self.calendar,actor,scope,source['item_id'],'task_due')
                    except (ValueError,PermissionError):continue
                    if source_digest(item)==source['digest']:titles.append(result['effects'][0]['title'])
            return '📋 Godkjente oppskriftskort\n'+'\n'.join('• '+title for title in titles[:8]) if titles else ''
