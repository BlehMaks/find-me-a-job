from pathlib import Path
import tempfile
import unittest

from fmj import campaign, tracking
from fmj.records import read_events
from fmj.workspace import create_workspace
from test_store import setup_policy


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'private';create_workspace(self.root);setup_policy(self.root)
        self.opp={'employer':'Synthetic Laboratory','url':'https://example.invalid/jobs/one',
            'title':'Researcher','resource_class':'official'}

    def test_url_receipt_reconciles_unknown_without_duplicate_or_portal_claim(self):
        op=campaign.create_operation(self.root,self.opp,'campaign')
        campaign.dispatch_operation(self.root,op['id'],'owner',lambda _: {'status':'delivery_unknown'},
            actual_form={'fields':{},'recipient':None,'attachments':[]},controlled=True)
        receipt={'employer':self.opp['employer'],'url':self.opp['url'],
                 'message_id':'synthetic-receipt-1','evidence':'Observed exact application acknowledgement'}
        self.assertTrue(campaign.match_receipt(self.root,op['id'],receipt))
        self.assertTrue(campaign.match_receipt(self.root,op['id'],receipt))
        result=campaign.load_operation(self.root,op['id'])
        self.assertEqual('submission_observed',result['stage'])
        self.assertEqual('matched_receipt',result['submission_basis'])
        self.assertEqual(1,campaign.status(self.root)['submission_count'])
        self.assertEqual(1,campaign.status(self.root)['acknowledgement_count'])
        self.assertEqual(1,tracking.report(self.root)['receipt_count'])

    def test_exact_receipt_establishes_unrecorded_submission_but_company_mail_does_not(self):
        op=campaign.create_operation(self.root,self.opp,'campaign')
        self.assertFalse(campaign.match_receipt(self.root,op['id'],{'employer':self.opp['employer'],'evidence':'General company email'}))
        self.assertEqual(0,campaign.status(self.root)['submission_count'])
        self.assertTrue(campaign.match_receipt(self.root,op['id'],{'employer':self.opp['employer'],'url':self.opp['url'],'evidence':'Exact receipt'}))
        self.assertEqual(1,campaign.status(self.root)['submission_count'])

    def test_interview_and_completed_assessment_survive_later_events(self):
        op=campaign.create_operation(self.root,self.opp,'campaign')
        campaign.observe_lifecycle(self.root,op['id'],'interview','Invitation message')
        campaign.observe_lifecycle(self.root,op['id'],'reply','Logistics reply')
        campaign.observe_lifecycle(self.root,op['id'],'assessment_completed','Candidate confirmed completion')
        campaign.observe_lifecycle(self.root,op['id'],'assessment_link_expired','Expired old link')
        current=campaign.load_operation(self.root,op['id'])
        self.assertEqual('interview',current['lifecycle'])
        self.assertIn('assessment_completed',current['milestones'])
        actions=tracking.query(self.root,'actions')
        self.assertEqual('completed',next(a for a in actions if a['kind']=='assessment')['status'])
        self.assertTrue(any(a['kind']=='verify_assessment_receipt' for a in actions))
        count=len(read_events(self.root))
        campaign.observe_lifecycle(self.root,op['id'],'assessment_completed','Candidate confirmed completion')
        self.assertEqual(count,len(read_events(self.root)))
        with self.assertRaises(ValueError):
            tracking.action(self.root,'assessment','owner',op['id'],action_id=next(a['id'] for a in actions if a['kind']=='assessment'))

    def test_next_conversation_turn_sends_once_and_refusal_persists(self):
        recipient={'channel':'email','address':'researcher@example.invalid'}
        def prepare(turn,body):
            return campaign.create_operation(self.root,self.opp,'campaign',action='send_message',recipient=recipient,
                purpose='reply',thread_id='thread-1',turn_id=turn,reply_to=turn,form_values={'body':body})
        one=prepare('inbound-1','First answer')
        campaign.dispatch_operation(self.root,one['id'],'owner',lambda _: {'status':'submission_observed','evidence':'Sent message 1'},
            actual_form={'fields':{'body':'First answer'},'recipient':recipient,'attachments':[]},controlled=True)
        two=prepare('inbound-2','Second answer')
        self.assertNotEqual(one['id'],two['id'])
        self.assertEqual(one['id'],prepare('inbound-1','First answer')['id'])
        tracking.contact(self.root,recipient['channel'],recipient['address'],refused=True)
        with self.assertRaises(campaign.CampaignBlocked):prepare('inbound-3','Another answer')


if __name__=='__main__':unittest.main()
