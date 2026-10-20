from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest
from fmj.__main__ import main

class CLITests(unittest.TestCase):
    def call(self,args):
        output=io.StringIO();errors=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):code=main(args)
        return code,output.getvalue(),errors.getvalue()
    def test_init_doctor_and_empty_record_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=str(Path(temp)/'private')
            code,out,err=self.call(['init','--workspace',root,'--agent','codex'])
            self.assertEqual(0,code,err)
            code,out,err=self.call(['doctor','--workspace',root,'--json'])
            self.assertEqual(0,code,err)
            self.assertTrue(json.loads(out)['ready_for_intake'])
            self.assertFalse(json.loads(out)['ready_for_outbound'])
            code,out,err=self.call(['validate','--workspace',root]);self.assertEqual(0,code,err)
    def test_init_never_overwrites_and_does_not_echo_private_input(self):
        with tempfile.TemporaryDirectory() as temp:
            args=['init','--workspace',str(Path(temp)/'private'),'--agent','codex']
            self.assertEqual(0,self.call(args)[0]);code,out,err=self.call(args)
            self.assertEqual(2,code);self.assertNotIn(temp,err)
    def test_feedback_enable_requires_explicit_target(self):
        with tempfile.TemporaryDirectory() as temp:
            code,out,err=self.call(['init','--workspace',str(Path(temp)/'private'),'--agent','codex','--feedback','enabled'])
            self.assertEqual(2,code)
    def test_controlled_fixture_bypass_not_available_in_cli(self):
        from fmj.__main__ import parser
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):parser().parse_args(['campaign','begin','--workspace','x','--operation','x','--input','x','--controlled'])

    def prepared_operation(self, root, action, recipient=None, form_values=None):
        from fmj.campaign import create_operation
        from fmj.records import save_record
        code, out, err = self.call(['init', '--workspace', str(root), '--agent', 'codex'])
        self.assertEqual(0, code, err)
        save_record(root, 'campaign-policy', {
            'id':'campaign-1', 'approved':True, 'markets':['example'], 'languages':['en'],
            'approved_titles':['Researcher'], 'hard_exclusions':{},
            'resource_classes':['official'], 'expansion_authority':False})
        observation = root / 'artifacts' / 'browser-observation.json'
        observation.write_text(json.dumps({'adapter':'synthetic-test', 'observed':'Connected inert browser fixture'}))
        code, _, err = self.call(['capability', '--workspace', str(root), '--name', 'browser',
            '--adapter', 'synthetic-test', '--evidence', str(observation)])
        self.assertEqual(0, code, err)
        operation = create_operation(root, {
            'employer':'Synthetic Institute', 'requisition_id':'R1', 'title':'Researcher',
            'resource_class':'official'}, 'campaign-1', action=action, recipient=recipient,
            form_values=form_values)
        actual = root / 'artifacts' / 'actual-form.json'
        actual.write_text(json.dumps({'fields':form_values or {}, 'recipient':recipient, 'attachments':[]}))
        return operation, actual

    def test_document_free_outreach_can_begin_with_exact_form_and_recipient(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            recipient = {'channel':'email', 'address':'researcher@example.invalid'}
            operation, actual = self.prepared_operation(root, 'send_message', recipient,
                {'body':'Synthetic inquiry about research opportunities.'})
            args = ['campaign', 'begin', '--workspace', str(root), '--operation', operation['id'], '--input', str(actual)]
            original = json.loads(actual.read_text())
            wrong = {**original, 'recipient':{**recipient, 'address':'wrong@example.invalid'}}
            actual.write_text(json.dumps(wrong))
            self.assertEqual(2, self.call(args)[0])
            actual.write_text(json.dumps(original))
            code, out, err = self.call(args)
            self.assertEqual(0, code, err)
            bridge = json.loads(out)
            self.assertTrue(bridge['ticket'])
            self.assertEqual('send_message', bridge['intent']['action'])
            self.assertIsNone(bridge['intent']['bundle'])
            self.assertEqual(2, self.call(args)[0])  # A begun native action cannot be duplicated.

    def test_application_without_cv_stays_blocked(self):
        from fmj.campaign import load_operation
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            operation, actual = self.prepared_operation(root, 'apply')
            code, _, _ = self.call(['campaign', 'begin', '--workspace', str(root),
                '--operation', operation['id'], '--input', str(actual)])
            self.assertEqual(2, code)
            self.assertEqual('ready', load_operation(root, operation['id'])['stage'])

    def test_text_only_document_gate_does_not_allow_unverified_attachments(self):
        from fmj.campaign import verify_operation_documents
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            self.prepared_operation(root, 'send_message', {'channel':'email', 'address':'researcher@example.invalid'}, {'body':'Synthetic message.'})
            for action in ('send_message', 'connect', 'follow_up'):
                self.assertTrue(verify_operation_documents(root, {'action':action, 'bundle':None, 'attachments':[]}))
                self.assertFalse(verify_operation_documents(root, {'action':action, 'bundle':None, 'attachments':[{'path':'synthetic.pdf'}]}))
            self.assertFalse(verify_operation_documents(root, {'action':'submit_proposal', 'bundle':None, 'attachments':[]}))

if __name__=='__main__':unittest.main()
