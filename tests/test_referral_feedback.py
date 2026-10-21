from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from fmj import campaign, store, tracking
from fmj.workspace import WorkspaceError, create_workspace
from test_store import setup_policy


class ReferralFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'private';create_workspace(self.root,time_zone='Europe/Berlin')
        setup_policy(self.root)
        self.opp={'employer':'Synthetic Laboratory','requisition_id':'R1','title':'Researcher','resource_class':'official'}

    def send(self, operation):
        return campaign.dispatch_operation(self.root,operation['id'],'owner',lambda _: {
            'status':'submission_observed','evidence':'Observed synthetic submission'},
            actual_form={'fields':{},'recipient':None,'attachments':[]},controlled=True)

    def test_referral_wait_blocks_only_its_opportunity(self):
        waiting=campaign.create_operation(self.root,{**self.opp,'referral_available':True},'campaign')
        with self.assertRaisesRegex(campaign.CampaignBlocked,'Referral wait'):
            self.send(waiting)
        other=campaign.create_operation(self.root,{**self.opp,'requisition_id':'R2'},'campaign')
        self.assertEqual('submission_observed',self.send(other)['stage'])
        wait=tracking.query(self.root,'referrals',waiting['opportunity_id'])[0]
        self.assertEqual('waiting',wait['status'])

    def test_weekend_timezone_deadline_and_contact_cap(self):
        opp=tracking.opportunity(self.root,self.opp)
        friday=datetime(2026,10,23,12,tzinfo=ZoneInfo('Europe/Berlin'))
        wait=tracking.referral(self.root,opp['id'],clock=friday)
        self.assertEqual('2026-10-28T12:00:00+01:00',wait['wait_until'])
        people=[tracking.contact(self.root,'email',f'person-{i}@example.invalid',company_id=opp['company_id'])['id'] for i in range(4)]
        tracking.referral(self.root,opp['id'],contacts=people[:3],clock=friday)
        with self.assertRaisesRegex(WorkspaceError,'limit'):
            tracking.referral(self.root,opp['id'],contacts=[people[3]],clock=friday)
        capped=tracking.opportunity(self.root,{**self.opp,'requisition_id':'R2','deadline':'2026-10-24T12:00:00+02:00'})
        self.assertEqual('2026-10-24T12:00:00+02:00',tracking.referral(self.root,capped['id'],clock=friday)['wait_until'])

    def test_freshness_requires_publication_evidence_and_refused_contacts_fail(self):
        current=datetime(2026,10,21,12,tzinfo=ZoneInfo('Europe/Berlin'))
        opp=tracking.opportunity(self.root,self.opp)
        with self.assertRaisesRegex(WorkspaceError,'verified freshness'):
            tracking.referral(self.root,opp['id'],status='direct',direct_reason='fresh_post',evidence='Discovered today',clock=current)
        opp=tracking.opportunity(self.root,{**self.opp,'published_at':(current-timedelta(hours=2)).isoformat(),'publication_evidence':'Observed posting date on employer site'})
        direct=tracking.referral(self.root,opp['id'],status='direct',direct_reason='fresh_post',evidence='Verified fresh employer posting',clock=current)
        self.assertEqual('direct',direct['status'])
        person=tracking.contact(self.root,'email','declined@example.invalid',company_id=opp['company_id'],refused=True)
        with self.assertRaisesRegex(WorkspaceError,'not refused'):
            tracking.referral(self.root,opp['id'],contacts=[person['id']],clock=current)

    def test_selected_referral_and_late_link_do_not_create_another_application(self):
        first=campaign.create_operation(self.root,self.opp,'campaign')
        self.send(first)
        person=tracking.contact(self.root,'email','employee@example.invalid',company_id=first['intent']['opportunity']['company_id'])
        tracking.referral(self.root,first['opportunity_id'],contacts=[person['id']],status='selected',selected_contact=person['id'],evidence='Late referral link received')
        again=campaign.create_operation(self.root,self.opp,'campaign')
        self.assertEqual(first['id'],again['id'])
        self.assertEqual('direct',campaign.load_operation(self.root,first['id'])['route_snapshot']['route'])

    def test_49_50_51_100_unique_submissions_prompt_once_without_pause(self):
        for index in range(1,101):
            op=campaign.create_operation(self.root,{**self.opp,'requisition_id':f'R{index}'},'campaign')
            self.send(op)
            if index in {49,50,51,100}:
                thresholds=[r['threshold'] for r in tracking.query(self.root,'reviews')]
                self.assertEqual([] if index==49 else [50] if index<100 else [50,100],thresholds)
        self.assertEqual(100,campaign.status(self.root)['submission_count'])
        self.assertFalse(campaign.status(self.root)['paused'])
        tracking.review(self.root,'campaign',50,'Broader research roles are still welcome','owner')
        self.assertEqual(1,len(tracking.report(self.root)['direction_reviews']))
        self.assertEqual(25,len(campaign.status(self.root)['operations']))

    def test_evidence_lookup_distinguishes_existing_experience_and_unknown(self):
        from fmj.records import save_record
        save_record(self.root,'fact',{'id':'skill','subject':'synthetic-project','field':'methods',
            'value':'Prepared research reports with Power BI','status':'candidate_confirmed',
            'confirmed_by':'candidate','confirmed_at':'2026-01-01T00:00:00Z'})
        matches=tracking.evidence(self.root,['PowerBI','Unverified Tool'])
        self.assertEqual('evidence_found',matches[0]['status'])
        self.assertEqual('unknown',matches[1]['status'])


if __name__=='__main__':unittest.main()
