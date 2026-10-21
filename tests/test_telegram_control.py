from pathlib import Path
import tempfile
import unittest
from fmj import campaign, telegram, store
from fmj.workspace import create_workspace, atomic_write_json


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'client'
        create_workspace(self.root,mode='managed',operator='operator',source_root=self.base/'source')
        campaign.bind_client(self.root,'client','operator',101,202,'browser')
    def update(self,number,text,chat=101,user=202):
        return {'update_id':number,'message':{'text':text,'chat':{'id':chat},'from':{'id':user}}}
    def test_bound_identity_and_update_idempotency(self):
        with self.assertRaises(campaign.AuthorityError):telegram.process_update(self.root,self.update(1,'/status',user=999))
        self.assertIsNotNone(telegram.process_update(self.root,self.update(1,'/pause')))
        self.assertIsNone(telegram.process_update(self.root,self.update(1,'/pause')))
    def test_client_resume_does_not_clear_operator_pause(self):
        campaign.set_pause(self.root,'operator','maintenance')
        telegram.process_update(self.root,self.update(1,'/pause'))
        telegram.process_update(self.root,self.update(2,'/resume'))
        self.assertTrue(campaign.status(self.root)['pauses'])
    def test_service_requests_do_not_change_campaign(self):
        result=telegram.process_update(self.root,self.update(1,'Change my salary target'))
        self.assertIn('operator',result['text'])
        self.assertFalse(campaign.status(self.root)['pauses'])

    def test_safe_request_content_and_operator_states_are_durable(self):
        update=self.update(1,'Please consider research roles in another market')
        update['message']['message_id']=77
        result=telegram.process_update(self.root,update)
        requests=telegram.inbox(self.root,'operator')
        self.assertEqual(1,len(requests))
        self.assertEqual(update['message']['text'],requests[0]['body'])
        self.assertEqual('received',requests[0]['status'])
        self.assertNotIn('routed',result['text'])
        self.assertIsNone(telegram.process_update(self.root,update))
        self.assertEqual(1,len(telegram.inbox(self.root,'operator')))
        with self.assertRaises(telegram.TelegramError):telegram.inbox(self.root,'client')
        seen=telegram.inbox(self.root,'operator',requests[0]['id'],'seen','Operator read the private request')
        self.assertEqual('seen',seen['status'])
        resolved=telegram.inbox(self.root,'operator',requests[0]['id'],'resolved','Operator answered separately')
        self.assertEqual('resolved',resolved['status'])

    def test_factual_reply_links_to_exact_question_without_command(self):
        question=self.question_setup()
        def transport(*args):
            from fmj.workspace import WorkspaceError
            with self.assertRaises(WorkspaceError):store.connection(self.root)
            return {'message_id':7}
        telegram.ask(self.root,question,'operator',transport=transport)
        update=self.update(1,'I personally used the verified research method')
        update['message']['reply_to_message']={'message_id':7}
        telegram.process_update(self.root,update)
        from fmj.records import load_record
        saved=load_record(self.root,'clarification',question['id'])
        self.assertEqual('answered',saved['status'])
        self.assertEqual(update['message']['text'],saved['answer'])
        self.assertEqual([],telegram.inbox(self.root,'operator'))
    def test_self_hosted_has_no_telegram(self):
        root=self.base/'local';create_workspace(root,source_root=self.base/'source')
        with self.assertRaises(telegram.TelegramError):telegram.process_update(root,self.update(1,'/pause'))
    def test_other_client_cannot_read_workspace(self):
        other=self.base/'other';create_workspace(other,mode='managed',operator='operator',source_root=self.base/'source')
        campaign.bind_client(other,'other-client','operator',303,404,'other-browser')
        with self.assertRaises(campaign.AuthorityError):telegram.process_update(other,self.update(1,'/status'))

    def test_lost_reply_preserves_notice_and_durable_retry(self):
        from fmj.records import load_record,save_record,read_events
        binding=load_record(self.root,'client-binding','client')
        binding['bot_secret_ref']='bot.txt';save_record(self.root,'client-binding',binding,actor='operator')
        secret=self.root/'secrets'/'bot.txt';secret.write_text('123:synthetic');secret.chmod(0o600)
        telegram.process_update(self.root,self.update(1,'/pause'))
        def fail(*a):raise telegram.TelegramError('network unavailable')
        result=telegram.flush_outbox(self.root,transport=fail)
        self.assertEqual(1,result['pending_notifications'])
        self.assertTrue(any(x['type']=='operator_attention_required' for x in read_events(self.root)))
        sent=[]
        telegram.flush_outbox(self.root,transport=lambda *a:sent.append(a) or {})
        self.assertEqual(1,len(sent))
        self.assertIsNone(telegram.process_update(self.root,self.update(1,'/pause')))

    def test_secret_looking_text_never_enters_journal(self):
        marker='SYNTHETIC_SECRET_SENTINEL'
        telegram.process_update(self.root,self.update(1,'password: '+marker))
        self.assertFalse(any(marker in p.read_text() for p in self.root.rglob('*.json')))
        self.assertFalse(any(marker in p.read_text() for p in self.root.rglob('*.jsonl')))
        self.assertNotIn(marker.encode(),(self.root/'career.sqlite3').read_bytes())

    def question_setup(self):
        from fmj.records import load_record, save_record
        binding = load_record(self.root, 'client-binding', 'client')
        binding['bot_secret_ref'] = 'bot.txt'
        save_record(self.root, 'client-binding', binding, actor='operator')
        secret = self.root / 'secrets' / 'bot.txt'
        secret.write_text('123:synthetic_private_bot_token')
        secret.chmod(0o600)
        return {'id':'question-1', 'question':'Which methods did you personally use?',
                'scope':{'type':'experience', 'experience_id':'project-1'},
                'intended_actor':'client', 'status':'pending'}

    def test_question_timeout_is_persisted_before_send_and_never_replayed(self):
        from fmj.workspace import read_json
        from fmj.records import load_record
        question = self.question_setup()
        intent_key = 'telegram-question:question-1'
        calls = []
        def accepted_but_timeout(token, method, payload):
            intent = store.state(self.root,intent_key)
            self.assertEqual('delivery_unknown', intent['status'])
            self.assertEqual('client', intent['identity']['client'])
            calls.append(payload)
            raise TimeoutError('Synthetic server accepted message but response was lost')
        with self.assertRaises(telegram.TelegramError):
            telegram.ask(self.root, question, 'operator', transport=accepted_but_timeout)
        with self.assertRaises(telegram.TelegramError):
            telegram.ask(self.root, question, 'operator', transport=lambda *args:self.fail('Question replayed'))
        self.assertEqual(1, len(calls))
        self.assertEqual('delivery_unknown', store.state(self.root,intent_key)['status'])
        self.assertEqual(1, load_record(self.root, 'clarification', question['id'])['version'])
        # The ordinary notification retry loop must not retry a factual question.
        telegram.flush_outbox(self.root, transport=lambda *args:self.fail('Question retried by reply outbox'))
        self.assertFalse(any('123:synthetic_private_bot_token' in path.read_text() for path in self.root.rglob('*.json')))

    def test_question_normal_delivery_is_idempotent_and_content_bound(self):
        from fmj.workspace import read_json
        from fmj.records import load_record
        question = self.question_setup()
        calls = []
        def delivered(token, method, payload):
            calls.append(payload)
            return {'message_id':7}
        first = telegram.ask(self.root, question, 'operator', transport=delivered)
        second = telegram.ask(self.root, question, 'operator', transport=lambda *args:self.fail('Delivered question replayed'))
        self.assertEqual('delivered', first['notification_status'])
        self.assertEqual(first, second)
        self.assertEqual(1, len(calls))
        intent = store.state(self.root,'telegram-question:question-1')
        self.assertEqual(7, intent['message_id'])
        self.assertEqual('delivered', intent['status'])
        with self.assertRaises(telegram.TelegramError):
            telegram.ask(self.root, {**question, 'question':'Changed factual question'}, 'operator', transport=lambda *args:self.fail('Changed same-ID question sent'))
        self.assertEqual(1, load_record(self.root, 'clarification', question['id'])['version'])
        telegram.ask(self.root, {**question, 'id':'question-2', 'question':'A separately reviewed new question'}, 'operator', transport=delivered)
        self.assertEqual(2, len(calls))

if __name__=='__main__':unittest.main()
