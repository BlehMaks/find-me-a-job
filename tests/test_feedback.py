from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from fmj import feedback
from fmj.workspace import create_workspace, read_json


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'client'
        create_workspace(self.root, source_root=Path(self.temp.name) / 'source')
        self.payload = dict(summary='Resume parser joins headings', expected='Readable words', observed='Joined words',
                            reproduction='Synthetic document with two headings', product_version='0.1', platform='macOS')

    def test_unset_and_disabled_consent_send_nothing(self):
        p = feedback.prepare(self.root, self.payload)
        feedback.review(self.root, p['id'], 'reviewer', True)
        for enabled in (None, False):
            if enabled is False: feedback.consent(self.root, False, 'example/product', 'owner')
            with self.assertRaises(feedback.FeedbackError):
                feedback.submit(self.root, p['id'], runner=lambda *a, **k: self.fail('sent'))

    def test_private_fields_and_addresses_rejected(self):
        for values in ({**self.payload, 'transcript': 'raw'}, {**self.payload, 'observed': 'person@'+'mail.test'}):
            with self.assertRaises(feedback.FeedbackError): feedback.prepare(self.root, values)

    def test_review_and_submission_are_bound_and_idempotent(self):
        feedback.consent(self.root, True, 'example/product', 'owner')
        p = feedback.prepare(self.root, self.payload)
        with self.assertRaises(feedback.FeedbackError): feedback.submit(self.root, p['id'])
        feedback.review(self.root, p['id'], 'reviewer', True)
        calls=[]
        def run(cmd, **kw):
            calls.append(cmd); return types.SimpleNamespace(stdout='https://github.com/example/product/issues/7\n')
        feedback.submit(self.root, p['id'], runner=run)
        with self.assertRaises(feedback.FeedbackError): feedback.submit(self.root, p['id'], runner=run)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('merge', calls[0])

    def test_uncertain_delivery_is_not_retried(self):
        feedback.consent(self.root, True, 'example/product', 'owner')
        p=feedback.prepare(self.root,self.payload);feedback.review(self.root,p['id'],'reviewer',True)
        def fail(*a,**k): raise subprocess.TimeoutExpired('gh',90)
        with self.assertRaises(feedback.FeedbackError):feedback.submit(self.root,p['id'],runner=fail)
        with self.assertRaises(feedback.FeedbackError):feedback.submit(self.root,p['id'],runner=lambda *a,**k:self.fail('retry'))

    def test_managed_client_cannot_enable_feedback(self):
        other=Path(self.temp.name)/'managed';create_workspace(other, mode='managed',operator='operator',source_root=Path(self.temp.name)/'source')
        with self.assertRaises(feedback.FeedbackError):feedback.consent(other, True,'example/product','owner')

if __name__ == '__main__': unittest.main()
