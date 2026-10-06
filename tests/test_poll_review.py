"""Parent review probes for poll identity, bounded previews and storage."""
from types import SimpleNamespace
import pytest
from features.poll_manager import PollManager, parse_poll_command, parse_vote
from core.intent_router import IntentRouter, BotIntent


def test_same_length_option_replacement_requires_reset(tmp_path):
    manager=PollManager(tmp_path/'polls.json')
    poll=manager.create_poll('g','Dinner?',['Pizza','Soup'],'Owner','1')
    manager.vote('g',poll['id'],1,'2','Voter')
    preview=manager.preview_poll_edit('g',poll['id'],{'options':['Fish','Soup']},'1')
    assert preview['effect']=='reset_votes' and preview['requires_confirmation'] is True
    assert manager.apply_poll_edit('g',poll['id'],'1',preview['token'])[0] is False


def test_explicit_option_label_edit_keeps_stable_id_votes(tmp_path):
    manager=PollManager(tmp_path/'polls.json')
    poll=manager.create_poll('g','Dinner?',['Pizza','Soup'],'Owner','1')
    manager.vote('g',poll['id'],1,'2','Voter')
    option_id=poll['options'][0]['id']
    preview=manager.preview_poll_edit('g',poll['id'],{'option_labels':{option_id:'Margherita'}},'1')
    assert preview['ok'] and preview['effect']=='preserve_votes'
    ok, changed=manager.apply_poll_edit('g',poll['id'],'1',preview['token'])
    assert ok and changed['options'][0]['id']==option_id and changed['options'][0]['votes']==['2']


def test_poll_preview_expires_and_is_bounded(tmp_path):
    tick=[10.0]
    manager=PollManager(tmp_path/'polls.json',monotonic=lambda:tick[0])
    poll=manager.create_poll('g','Dinner?',['A','B'],'Owner','1')
    first=manager.preview_poll_edit('g',poll['id'],{'options':['C']},'1')
    tick[0]=311
    assert manager.apply_poll_edit('g',poll['id'],'1',first['token'],confirm_reset=True)[0] is False
    for _ in range(200):
        manager.preview_poll_edit('g',poll['id'],{'options':['C']},'1')
    assert len(manager._edit_previews)<=128


@pytest.mark.parametrize('original',[b'{corrupt',b'{"schema_version":99,"document":{}}'])
def test_corrupt_or_newer_poll_store_is_preserved_and_cannot_be_written(tmp_path, original):
    from utils.storage_contract import StorageMutationError
    path=tmp_path/'polls.json';path.write_bytes(original)
    manager=PollManager(path)
    with pytest.raises(StorageMutationError):
        manager.create_poll('g','No overwrite',['A','B'],'Owner','1')
    assert path.read_bytes()==original


def test_poll_results_and_confirmation_route_with_real_mentions(tmp_path):
    manager=PollManager(tmp_path/'polls.json')
    router=IntentRouter(SimpleNamespace(poll=manager,parse_poll_command=parse_poll_command,parse_vote=parse_vote))
    for mention in ('@inebotten','<@123>','<@!123>'):
        assert router.route(f'{mention} poll results',guild_id='g').intent is BotIntent.POLL_LIST
        result=router.route(f'{mention} bekreft poll endring {"a"*32} reset',guild_id='g')
        assert result.intent is BotIntent.POLL_EDIT
        assert result.payload['poll_edit']['confirm_token']=='a'*32


def test_poll_console_excludes_expired_active_record_after_restart(tmp_path,monkeypatch):
    from web_console.state_collector import collect_poll_data
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    manager=PollManager(tmp_path/'discord/data/polls.json')
    poll=manager.create_poll('g','Expired',['A','B'],'Owner','1')
    records=manager.polls
    records['g'][poll['id']]['expires_at']='2000-01-01T00:00:00'
    manager.polls=records
    manager._save_polls()
    assert collect_poll_data()['active_polls']==0


def test_structural_edit_is_not_reinterpreted_as_new_poll_creation(tmp_path):
    manager=PollManager(tmp_path/'polls.json')
    manager.create_poll('g','Existing?',['A','B'],'Owner','1')
    router=IntentRouter(SimpleNamespace(poll=manager,parse_poll_command=parse_poll_command,parse_vote=parse_vote))
    result=router.route('@inebotten endre poll 1 valg: Fish/Soup',guild_id='g')
    assert result.intent is BotIntent.POLL_EDIT
    assert result.payload['poll_edit']['changes']=={'options':['Fish','Soup']}


def test_poll_return_is_a_snapshot_and_another_writer_is_refused(tmp_path):
    from utils.storage_contract import StorageMutationError
    path=tmp_path/'polls.json'
    first=PollManager(path)
    poll=first.create_poll('g','Snapshot',['A','B'],'Owner','1')
    poll['options'][0]['votes'].append('forged')
    assert first.get_poll('g',poll['id'])['options'][0]['votes']==[]
    other=PollManager(path)
    with pytest.raises(StorageMutationError,match='store_owned'):
        other.vote('g',poll['id'],1,'2','Voter')
    first.close_storage();other.close_storage()
