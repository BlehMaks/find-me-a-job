import json
from pathlib import Path
import tempfile
import unittest

from fmj import store, tracking
from fmj.campaign import create_operation, dispatch_operation, load_operation, refresh_operation
from fmj.records import append_event, read_events, save_record
from fmj.workspace import WorkspaceError, atomic_write_json, create_workspace, load_workspace, locked_workspace


def setup_policy(root):
    return save_record(root, 'campaign-policy', {'id':'campaign', 'approved':True,
        'markets':['example'], 'languages':['en'], 'approved_titles':['Researcher'],
        'hard_exclusions':{}, 'resource_classes':['official'], 'expansion_authority':True})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        create_workspace(self.root)
        setup_policy(self.root)
        self.opp = {'employer':'Synthetic Laboratory', 'url':'https://example.invalid/jobs/one',
                    'title':'Researcher', 'resource_class':'official'}

    def test_nested_effect_and_event_rollback_together(self):
        count = len(read_events(self.root))
        with self.assertRaises(RuntimeError):
            with locked_workspace(self.root):
                tracking.opportunity(self.root, self.opp)
                append_event(self.root, 'discovered')
                raise RuntimeError('interruption')
        self.assertEqual(count, len(read_events(self.root)))
        self.assertEqual([], tracking.query(self.root, 'opportunities'))

    def test_alias_enrichment_purpose_and_campaign_do_not_duplicate(self):
        first = create_operation(self.root, self.opp, 'campaign')
        result = dispatch_operation(self.root, first['id'], 'owner', lambda _: {
            'status':'submission_observed','evidence':'Synthetic portal success'},
            actual_form={'fields':{},'recipient':None,'attachments':[]}, controlled=True)
        again = create_operation(self.root, {**self.opp,'requisition_id':'REQ1'}, 'campaign', purpose='another label')
        self.assertEqual(result['id'], again['id'])
        self.assertEqual(1, tracking.report(self.root)['applications'])
        self.assertEqual(1, len(tracking.query(self.root, 'companies')))
        self.assertEqual(2, len(store.rows(self.root, 'SELECT * FROM opportunity_aliases')))

    def test_unsent_refresh_retains_history(self):
        first = create_operation(self.root, self.opp, 'campaign')
        setup_policy(self.root)
        updated = refresh_operation(self.root, first['id'], {'form_values':{'answer':'Corrected'}})
        self.assertEqual(first['application_id'], updated['application_id'])
        self.assertEqual(2, updated['revision'])
        self.assertEqual('superseded', load_operation(self.root, first['id'])['stage'])
        self.assertEqual({}, load_operation(self.root, first['id'])['intent']['form_values'])

    def test_company_alias_conflict_and_group_cycle(self):
        a = tracking.company(self.root, 'Synthetic A')
        b = tracking.company(self.root, 'Synthetic B', parent_id=a['id'], group_evidence='Published group ownership')
        with self.assertRaises(WorkspaceError):
            tracking.company(self.root, 'Synthetic A', aliases=['Synthetic B'])
        with self.assertRaises(WorkspaceError):
            tracking.company(self.root, 'Synthetic A', parent_id=b['id'], group_evidence='Invalid cycle')

    def test_safe_backup_restore_and_later_send_protection(self):
        first = create_operation(self.root, self.opp, 'campaign')
        backup = self.root/'runtime'/'snapshot.sqlite3'
        store.backup(self.root, backup)
        tracking.company(self.root, 'Additional Synthetic Company')
        self.assertEqual('restored', store.restore(self.root, backup)['status'])
        self.assertEqual(1, len(tracking.query(self.root, 'companies')))
        dispatch_operation(self.root, first['id'], 'owner', lambda _: {
            'status':'submission_observed','evidence':'Synthetic submission'},
            actual_form={'fields':{},'recipient':None,'attachments':[]}, controlled=True)
        with self.assertRaisesRegex(WorkspaceError, 'later observed'):
            store.restore(self.root, backup)

    def make_legacy(self, corrupt=False):
        operation = create_operation(self.root, self.opp, 'campaign')
        events = read_events(self.root)
        for event in events:
            atomic_write_json(self.root/'events'/f"{event['sequence']:08d}.json", event)
        atomic_write_json(self.root/'operations'/(operation['id']+'.json'), operation)
        config = load_workspace(self.root)
        atomic_write_json(self.root/'workspace.json', {**config,'schema_version':1})
        (self.root/'career.sqlite3').unlink()
        if corrupt:
            path = next((self.root/'events').glob('*.json'))
            data = json.loads(path.read_text()); data['actor']='modified'
            atomic_write_json(path, data)
        return operation, len(events)

    def test_migration_inspection_reimport_and_originals(self):
        operation, count = self.make_legacy()
        result = store.migrate(self.root)
        self.assertEqual('validated_dry_run', result['status'])
        self.assertFalse((self.root/'career.sqlite3').exists())
        self.assertEqual('migrated', store.migrate(self.root, apply=True)['status'])
        self.assertEqual('already_current', store.migrate(self.root, apply=True)['status'])
        self.assertEqual(count, len(read_events(self.root)))
        self.assertEqual(operation['intent_hash'], load_operation(self.root, operation['id'])['intent_hash'])
        self.assertTrue((self.root/'runtime'/'legacy-before-sqlite.zip').exists())
        self.assertTrue((self.root/'operations'/(operation['id']+'.json')).exists())

    def test_corrupt_migration_does_not_cut_over(self):
        self.make_legacy(corrupt=True)
        with self.assertRaisesRegex(WorkspaceError, 'corrupted'):
            store.migrate(self.root, apply=True)
        self.assertEqual(1, load_workspace(self.root)['schema_version'])
        self.assertFalse((self.root/'career.sqlite3').exists())

    def test_missing_database_never_silently_starts_an_empty_history(self):
        (self.root/'career.sqlite3').unlink()
        with self.assertRaisesRegex(WorkspaceError,'missing'):
            tracking.report(self.root)
        self.assertFalse((self.root/'career.sqlite3').exists())

    def test_committed_migration_with_interrupted_cutover_recovers_once(self):
        self.make_legacy()
        store.migrate(self.root,apply=True)
        count=len(read_events(self.root))
        config=load_workspace(self.root)
        atomic_write_json(self.root/'workspace.json',{**config,'migration_pending':True,'storage_initialized':False})
        with self.assertRaisesRegex(WorkspaceError,'interrupted'):
            read_events(self.root)
        self.assertEqual('migrated',store.migrate(self.root,apply=True)['status'])
        self.assertEqual(count,len(read_events(self.root)))

    def test_restore_missing_database_recovers_with_reconciliation_pause(self):
        snapshot=self.root/'runtime'/'recover.sqlite3'
        store.backup(self.root,snapshot)
        (self.root/'career.sqlite3').unlink()
        self.assertTrue(store.restore(self.root,snapshot)['reconciliation_required'])
        from fmj.campaign import status
        self.assertTrue(status(self.root)['paused'])

    def test_malformed_same_workspace_backup_cannot_replace_live_storage(self):
        import sqlite3
        snapshot=self.root/'runtime'/'malformed.sqlite3'
        with sqlite3.connect(snapshot) as db:
            db.executescript('CREATE TABLE metadata(key,value);CREATE TABLE operations(id,stage,payload);')
            db.execute('INSERT INTO metadata VALUES(?,?)',('workspace_id',load_workspace(self.root)['id']))
        with self.assertRaisesRegex(WorkspaceError,'schema'):
            store.restore(self.root,snapshot)
        self.assertEqual(0,tracking.report(self.root)['applications'])

    def test_migration_uses_submission_event_over_stale_ready_snapshot(self):
        op=create_operation(self.root,self.opp,'campaign')
        append_event(self.root,'dispatch_started',operation_id=op['id'])
        append_event(self.root,'submission_observed',operation_id=op['id'],evidence='Synthetic portal acknowledgement')
        for event in read_events(self.root):
            atomic_write_json(self.root/'events'/f"{event['sequence']:08d}.json",event)
        atomic_write_json(self.root/'operations'/(op['id']+'.json'),op)
        atomic_write_json(self.root/'workspace.json',{**load_workspace(self.root),'schema_version':1})
        (self.root/'career.sqlite3').unlink()
        store.migrate(self.root,apply=True)
        self.assertEqual('submission_observed',load_operation(self.root,op['id'])['stage'])
        self.assertEqual(1,tracking.report(self.root)['applications'])

    def test_alias_conflict_rolls_back_cutover(self):
        operation, _ = self.make_legacy()
        import copy
        from fmj.records import _digest
        (self.root/'operations'/(operation['id']+'.json')).unlink()
        for key, req, url in [('a','shared','a'),('b','other','b'),('c','shared','b')]:
            value=copy.deepcopy(operation);value['id']=key
            value['intent']['opportunity'].update(requisition_id=req,url='https://example.invalid/'+url)
            value['intent_hash']=_digest(value['intent'])
            atomic_write_json(self.root/'operations'/(value['id']+'.json'),value)
        with self.assertRaisesRegex(WorkspaceError,'conflict'):
            store.migrate(self.root,apply=True)
        self.assertEqual(1,load_workspace(self.root)['schema_version'])
        self.assertEqual(3,len(list((self.root/'operations').glob('*.json'))))


if __name__ == '__main__':
    unittest.main()
