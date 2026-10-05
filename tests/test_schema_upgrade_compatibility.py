"""A new reader may migrate an old envelope; old code must refuse the result."""
import json

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
