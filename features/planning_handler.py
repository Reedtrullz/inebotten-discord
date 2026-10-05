"""Discord adaptation for explicit group planning commands."""
from datetime import datetime

from cal_system.event_schema import EventTime
from core.request_context import RequestContext, request_scope
from features.base_handler import BaseHandler
from features.poll_manager import PollStorageError
from utils.storage_contract import StorageMutationError

HELP = ('Planlegg én aktivitet: `planlegg Film | 04.01.2027 18:00 / 05.01.2027 18:00 | 120`. '
    'Dato/tid er Europe/Oslo; siste felt er varighet i minutter. '
    '`planlegg film #2 | … | 120` velger oppføring 2 i denne samtalens filmliste. '
    'Bruk `plan stem ID 1`, `plan vurder ID` eller `plan velg ID 1`. '
    'Deretter `plan bekreft ID TOKEN`. Varsler krever `varsle her` i forhåndsvisningen. '
    '`plan rsvp ID ja synlighet arrangør` deler med arrangøren; `meg` er privat og `gruppe` er synlig for gruppen.')


class PlanningHandler(BaseHandler):
    def __init__(self, monitor):
        super().__init__(monitor)
        self.planning=getattr(monitor,'planning',None)

    async def handle_planning(self, message, payload):
        if payload['action']=='help':
            await self.send_response(message,HELP);return
        if self.planning is None:
            await self.send_response(message,'Gruppeplanlegging er ikke tilgjengelig.');return
        actor=self.request_context or RequestContext.from_message(message,'no')
        try:
            with request_scope(actor):
                scope=self.planning.calendar.scope_key(operation='read' if payload['action'] in ('view','vote','rsvp') else 'write')
            action=payload['action'];session_id=payload.get('session_id')
            if action=='create':
                times=[]
                for raw in payload['candidates']:
                    parsed=datetime.strptime(raw,'%d.%m.%Y %H:%M')
                    times.append(EventTime('event',parsed.date(),parsed.time(),'Europe/Oslo',False,payload['duration']))
                if payload.get('watchlist_index'):
                    session=self.planning.create_from_watchlist(actor,scope,payload['watchlist_index'],times)
                else:
                    session=self.planning.create(actor,scope,payload['title'],times)
                labels=['🗳️ '+session['title'],f"Plan-ID: `{session['session_id']}`"]
                labels.extend(f"{i}. {value.local_date:%d.%m.%Y} kl. {value.local_time:%H:%M} — {value.duration_minutes} min" for i,value in enumerate(times,1))
                labels.append(f"Stem med `plan stem {session['session_id']} 1`. Arrangøren må gjennomgå og bekrefte; ingen tid er avtalt ennå.")
                await self.send_response(message,'\n'.join(labels))
            elif action=='view':
                session=self.planning.get_session(actor,session_id)
                lines=[f"📋 {session['title']} — {session['state']}"]
                lines.extend(f"{i}. {value['text']}: {value['count']} stemmer" for i,value in enumerate(session['votes'],1))
                lines.extend(f"RSVP {value['user_id']}: {value['response']} ({value['visibility']})" for value in session['rsvps'][:20])
                if session['event_id']:lines.append('Kalender-ID: '+session['event_id'])
                if session.get('reconciliation_pending'):lines.append('Kalenderpunktet finnes; planens kvittering må avstemmes ved ny bekreftelse.')
                await self.send_response(message,'\n'.join(lines)[:1700])
            elif action=='vote':
                self.planning.vote(actor,session_id,payload['selection'])
                await self.send_response(message,'✅ Stemmen er lagret. Avstemningen avtaler ikke tidspunkt automatisk.')
            elif action=='rsvp':
                result=self.planning.rsvp(actor,session_id,payload['response'],visibility=payload['visibility'])
                audience={'self':'bare deg','organizer':'deg og arrangøren','group':'den godkjente gruppen'}[result['visibility']]
                await self.send_response(message,f'✅ RSVP er lagret og synlig for {audience}. Ingen invitasjon er sendt.')
            elif action=='cancel':
                self.planning.cancel(actor,session_id)
                await self.send_response(message,'✅ Planleggingen er avbrutt. Ingen kalenderpunkt er opprettet.')
            elif action=='preview':
                preview=self.planning.preview_finalize(actor,session_id,selection=payload['selection'],notify=payload['notify'])
                effect=preview.effects[0]['after']; time=effect['time']
                text=f"Forhåndsvisning: {effect['title']} — {time['date']} kl. {time['time']} ({time['timezone']}), {time['duration_minutes']} min."
                text+='\nVarsler i denne samtalen er godkjent.' if effect['notify'] else '\nVarsler er av. RSVP blir ikke kalenderinvitasjoner.'
                text+=f"\nBekreft innen fem minutter med `plan bekreft {session_id} {preview.token}`."
                await self.send_response(message,text)
            else:
                result=await self.planning.finalize(actor,session_id,payload['token'])
                text='✅ Ett lokalt kalenderpunkt er bekreftet: '+result['event_id']
                if result['status']=='finalized_reconciliation_pending':text+='\nPlanens kvittering venter på avstemming. Ny bekreftelse oppretter ikke en kopi.'
                await self.send_response(message,text)
        except (ValueError,PermissionError,StorageMutationError,PollStorageError) as error:
            if str(error)=='explicit_selection_required':
                text='Avstemningen har null stemmer eller delt ledelse. Arrangøren må velge et alternativ med `plan velg ID N`.'
            else:
                text='Planendringen ble ikke utført. Kontroller arrangør/område, stemmer og datoer; lag en ny forhåndsvisning. Ingen privat kalender eller invitasjoner brukes.'
            await self.send_response(message,'❌ '+text)
