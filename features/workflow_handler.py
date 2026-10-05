"""Explicit reviewed recipe controls through the shared Discord sender."""
from features.base_handler import BaseHandler
from core.request_context import RequestContext,request_scope
from features.workflow_manager import TEMPLATES
from utils.storage_contract import StorageMutationError

HELP=('Oppskrifter starter pauset. `oppskrift ny forbered budsjett 10` lagrer oppgaveutkast fra et kalenderpunkt; '
    '`oppskrift ny forfalt budsjett 10` lager kort fra en forfalt oppgave. '
    '`oppskrift på ID`, `oppskrift pause ID`, `oppskrift vis`, `oppskrift historikk ID`. '
    'Velg kilde med `oppskrift vurder ID KALENDER-ID`, og bekreft med `oppskrift bekreft TOKEN`. '
    'Utkast oppretter ingen kalenderoppgave. Digest krever i tillegg egne varselvalg og `varsler kort oppskrifter`.')


class WorkflowHandler(BaseHandler):
    def __init__(self,monitor):
        super().__init__(monitor)
        self.workflows=getattr(monitor,'workflows',None)

    async def handle_workflow(self,message,payload):
        if payload['action']=='help':await self.send_response(message,HELP);return
        if self.workflows is None:await self.send_response(message,'Oppskrifter er ikke tilgjengelige.');return
        actor=self.request_context or RequestContext.from_message(message,'no')
        action=payload['action']
        try:
            if action=='create':
                with request_scope(actor):scope=self.workflows.calendar.scope_key(operation='write')
                recipe=await self.workflows.create_recipe(actor,scope,payload['template_id'],action_budget=payload['budget'])
                text=f"✅ Pauset oppskrift `{recipe['recipe_id']}` i {scope}. Budsjett {recipe['action_budget']}. Aktiver og gjennomgå en konkret kilde før bruk."
            elif action=='list':
                records=self.workflows.list_recipes(actor)
                text='\n'.join(f"`{v['recipe_id']}` · {v['template_id']} · {'på' if v['enabled'] else 'pauset'} · {v['used']}/{v['action_budget']}" for v in records) or 'Ingen oppskrifter i denne samtalen.'
            elif action=='enabled':
                await self.workflows.set_enabled(actor,payload['recipe_id'],payload['enabled'])
                text='✅ Oppskriften er '+('på. Kjøring krever fortsatt gjennomgang og bekreftelse.' if payload['enabled'] else 'pauset.')
            elif action=='history':
                records=self.workflows.history(actor,payload['recipe_id'])
                text='\n'.join(f"{v['execution_id'][:12]} · {v['effects'][0]['title']} · {v['delivery_status']}" for v in records[-8:]) or 'Ingen godkjente kjøringer.'
            elif action=='preview':
                recipe=self.workflows._recipe(actor,payload['recipe_id'])
                receipt=self.workflows.calendar.workflow_receipt(actor,recipe['scope_id'],payload['item_id'],TEMPLATES[recipe['template_id']])
                preview=self.workflows.preview_recipe(actor,payload['recipe_id'],receipt)
                effect=preview.effects[0]['after']['effect']
                text=f"Forhåndsvisning: {effect['title']} ({effect['date']}). Effekt: {effect['kind']}. Ingen utsending eller kalenderendring.\nBekreft innen fem minutter: `oppskrift bekreft {preview.token}`"
            else:
                result=await self.workflows.execute_confirmed(actor,payload['token'])
                effect=result['effects'][0]
                text=f"✅ Godkjent {effect['kind']}: {effect['title']} ({effect['date']}). Kjøring `{result['execution_id'][:12]}`. Ingen melding er sendt."
            await self.send_response(message,text[:1800])
        except (ValueError,PermissionError,StorageMutationError):
            await self.send_response(message,'❌ Oppskriften ble ikke kjørt. Kontroller eget område, samtale, på/pauset, budsjett og kilde; lag en ny forhåndsvisning.')
