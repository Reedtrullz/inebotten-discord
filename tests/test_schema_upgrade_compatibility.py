"""A new reader may migrate an old envelope; old code must refuse the result."""
import json
import pytest

from utils.storage_contract import DocumentOwner, bucket_records, load_document


def test_explicit_schema_upgrade_preserves_bytes_and_blocks_old_reader(tmp_path):
    path=tmp_path/'calendar.json'
    original=b'{"schema_version":1,"revision":4,"document":{"shared":[{"id":"fixture","title":"Behold"}]}}\n'
    path.write_bytes(original)
    owner=DocumentOwner(path,bucket_records('title',require_ids=True),schema_version=2,upgrade_from=(1,))
    try:
        assert owner.state.status=='valid' and owner.revision==4
        assert path.read_bytes()==original
        document=owner.rollback();document['shared'][0]['series']={'fixture':'new-semantics'}
        assert owner.commit(document).ok
        assert path.with_name('calendar.json.schema-v1.bak').read_bytes()==original
        value=json.loads(path.read_bytes())
        assert value['schema_version']==2 and value['revision']==5
        assert load_document(path,1).status=='unsupported'
        old=DocumentOwner(path,bucket_records('title'),schema_version=1)
        try:
            assert old.state.status=='unsupported'
            assert path.read_bytes()!=original
        finally:old.close()
    finally:owner.close()


def test_schema_upgrade_backup_conflict_preserves_original_and_refuses_commit(tmp_path):
    path=tmp_path/'calendar.json'
    original=b'{"schema_version":1,"document":{"shared":[]}}'
    path.write_bytes(original)
    backup=path.with_name('calendar.json.schema-v1.bak');backup.write_bytes(b'previous-generation')
    owner=DocumentOwner(path,bucket_records('title'),schema_version=2,upgrade_from=(1,))
    try:
        result=owner.commit({'shared':[]})
        assert not result.ok and result.error_code=='backup_conflict'
        assert path.read_bytes()==original and backup.read_bytes()==b'previous-generation'
    finally:owner.close()


def test_new_schema_is_not_implicitly_accepted_by_upgrade_reader(tmp_path):
    path=tmp_path/'calendar.json';path.write_text('{"schema_version":3,"document":{}}')
    owner=DocumentOwner(path,bucket_records('title'),schema_version=2,upgrade_from=(1,))
    try:assert owner.state.status=='unsupported'
    finally:owner.close()


async def test_backup_upgrade_is_a_copy_and_old_bundle_remains_readable(tmp_path,monkeypatch):
    from utils import backup_bundle as backup
    root=tmp_path/'source';root.mkdir()
    path=root/'calendar.json'
    original=b'{"schema_version":1,"revision":4,"document":{"shared":[{"id":"fixture","title":"Behold"}]}}'
    path.write_bytes(original)
    old_owner=DocumentOwner(path,bucket_records('title'),schema_version=1)
    try:
        old_archive=tmp_path/'old.zip'
        with monkeypatch.context() as legacy:
            legacy.setitem(backup.STORE_SCHEMAS,'calendar.json',1)
            await backup.create_bundle(backup.StoreRegistry(root,{'calendar.json':old_owner}),old_archive)
    finally:old_owner.close()
    monkeypatch.setitem(backup.STORE_SCHEMAS,'calendar.json',2)
    new_owner=DocumentOwner(path,bucket_records('title'),schema_version=2,upgrade_from=(1,))
    try:
        archive=tmp_path/'new.zip'
        manifest=await backup.create_bundle(backup.StoreRegistry(root,{'calendar.json':new_owner}),archive)
        assert path.read_bytes()==original
        assert manifest['stores'][0]['schema_version']==2
        new_preview=backup.validate_bundle(archive,tmp_path/'new-stage',tmp_path/'new-destination')
        old_preview=backup.validate_bundle(old_archive,tmp_path/'old-stage',tmp_path/'old-destination')
        assert new_preview.schema_versions==(('calendar.json',2),)
        assert old_preview.schema_versions==(('calendar.json',1),)
        backup.restore(old_preview,tmp_path/'old-destination',services_stopped=True)
        assert (tmp_path/'old-destination'/'calendar.json').read_bytes()==original
    finally:new_owner.close()


@pytest.mark.parametrize('kind',['calendar','reminders'])
def test_recurring_owner_migrates_v1_to_v2_and_preserves_original(kind,tmp_path):
    import asyncio
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_manager import ReminderManager
    from utils.deployment_contract import DeploymentManifest,DeploymentError,store_schemas
    path=tmp_path/(kind+'.json')
    original=json.dumps({'schema_version':1,'revision':4,'document':{'shared':[{
        'id':'old','title':'Fixture','text':'Fixture','date':'04.01.2027','due_date':'04.01.2027',
        'recurrence':'weekly','completed':False,'created_at':'2027-01-01T00:00:00'}]}}).encode()+b'\n'
    path.write_bytes(original)
    manager=(CalendarManager if kind=='calendar' else ReminderManager)(storage_path=path)
    try:
        assert manager._storage.schema_version==2
        assert path.read_bytes()==original  # initialization only reads
        if kind == 'calendar':
            asyncio.run(manager.setup())
        else:
            assert manager.complete_reminder('shared', reminder_id='old')[0]
        assert json.loads(path.read_bytes())['schema_version']==2
        assert path.with_name(path.name+'.schema-v1.bak').read_bytes()==original
        assert load_document(path,1).status=='unsupported'
        schemas=store_schemas(tmp_path)
        old=DeploymentManifest('a'*40,'sha256:'+'1'*64,1,0,1)
        with pytest.raises(DeploymentError,match='incompatible_data'):old.require_compatible(schemas)
        DeploymentManifest('b'*40,'sha256:'+'2'*64,1,0,2).require_compatible(schemas)
    finally:manager._storage.close()
