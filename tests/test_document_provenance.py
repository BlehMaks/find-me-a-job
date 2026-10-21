import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from fmj import documents
from fmj.campaign import CampaignBlocked, begin_dispatch, create_operation, verify_operation_documents
from fmj.records import load_record, save_record
from fmj.workspace import create_workspace
from test_store import setup_policy


def seed_fields(root, content, profile):
    result = {}
    for pointer, value in documents.factual_fields(content, profile).items():
        key = 'field-'+hashlib.sha256(pointer.encode()).hexdigest()[:20]
        save_record(root,'fact',{'id':key,'subject':'synthetic-candidate','field':pointer,
            'value':value,'status':'candidate_confirmed','confirmed_by':'synthetic-candidate',
            'confirmed_at':'2026-01-01T00:00:00+00:00'})
        result[pointer]=key
    return result


@unittest.skipUnless(shutil.which('xelatex') and shutil.which('pdftoppm'), 'real document tools unavailable')
class DocumentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'private';self.config=create_workspace(self.root)
        setup_policy(self.root)
        self.content=json.loads((documents.ROOT/'tests/fixtures/documents/industry.json').read_text())
        self.profile=documents.select_templates('industry')[0]
        self.fields=seed_fields(self.root,self.content,self.profile)
        bullet='/experience/0/bullets/0'
        save_record(self.root,'claim',{'id':'achievement','fact_ids':[self.fields[bullet]],
            'safe_wording':self.content['experience'][0]['bullets'][0]['text'],'status':'approved'})
        self.output=self.root/'different-catalog'/'reviewed'
        built=documents.build_bundle(self.content,self.profile,self.output,workspace=self.root)
        pages=[f'{mode}:{page}' for mode,count in built['verification']['pages'].items() for page in range(1,count+1)]
        documents.record_review(self.output,'synthetic-independent-review-fixture',[],pages,
            independent=True,reviewed_dimensions=['factual','vacancy_fit','visual'])
        self.bundle={'workspace_id':self.config['id'],'directory':str(self.output),
            'artifact_hashes':built['manifest']['artifact_hashes']}
        pdf=self.output/'standard.pdf'
        self.attachment={'field':'cv','role':'cv','path':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
            'workspace_id':self.config['id'],'mime_type':'application/pdf'}
        self.opp={'employer':'Synthetic Laboratory','requisition_id':'R1','title':'Researcher','resource_class':'official'}

    def intent(self, attachment=None):
        return {'action':'apply','bundle':self.bundle,'attachments':[attachment or self.attachment]}

    def test_wrong_real_pdf_cannot_authorize_dispatch(self):
        self.assertTrue(verify_operation_documents(self.root,self.intent()))
        other=self.root/'other-catalog';other.mkdir()
        other_pdf=other/'standard.pdf';shutil.copyfile(self.output/'standard.pdf',other_pdf)
        wrong={**self.attachment,'path':str(other_pdf)}
        self.assertFalse(verify_operation_documents(self.root,self.intent(wrong)))
        operation=create_operation(self.root,self.opp,'campaign',bundle=self.bundle,attachments=[wrong])
        with self.assertRaises(CampaignBlocked):
            begin_dispatch(self.root,operation['id'],'owner',{'fields':{},'recipient':None,'attachments':[wrong]},
                lambda intent:verify_operation_documents(self.root,intent))

    def test_fact_correction_blocks_current_document_but_unrelated_edit_does_not(self):
        save_record(self.root,'fact',{'id':'unrelated','subject':'other','field':'other','value':'Other detail',
            'status':'candidate_confirmed','confirmed_by':'candidate','confirmed_at':'2026-01-01T00:00:00Z'})
        self.assertTrue(verify_operation_documents(self.root,self.intent()))
        fact=load_record(self.root,'fact',self.fields['/experience/0/bullets/0'])
        fact['value']='Redesigned a review process and reduced median turnaround by 5%.'
        save_record(self.root,'fact',fact)
        self.assertFalse(verify_operation_documents(self.root,self.intent()))
        self.assertFalse(documents.finalize_bundle(self.output,self.root)['ready'])

    def test_missing_or_blanket_pointer_is_rejected(self):
        frozen=json.loads((self.output/'canonical.json').read_text())
        frozen['dependencies'].pop()
        with self.assertRaises(ValueError):documents.verify_dependencies(self.root,frozen,self.profile)
        frozen['dependencies'][0]['pointer']='/'
        with self.assertRaises(ValueError):documents.bind_dependencies(self.root,frozen,self.profile)

    def test_review_pack_preserves_hash_bound_approval(self):
        self.assertEqual('awaiting_independent_human_or_agent_review',documents.review_pack(self.output)['status'])
        self.assertTrue(documents.finalize_bundle(self.output,self.root)['ready'])


if __name__=='__main__':unittest.main()
