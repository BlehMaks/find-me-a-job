"""Synthetic local ATS + real CLI/SQL/TeX/PDF journey. Never contacts employers."""
import base64
from email.parser import BytesParser
from email.policy import default
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from fmj import documents


class FixtureATS(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body=b'''<!doctype html><html lang="en"><title>Synthetic ATS test</title>
        <h1>Synthetic Researcher application</h1><p>Local test only. No employer receives data.</p>
        <form method="post" action="/apply" enctype="multipart/form-data">
        <label>Name <input name="name" value="Synthetic Candidate"></label>
        <label>Opportunity <input name="job" value="browser-check"></label>
        <label>CV <input type="file" name="cv" accept=".pdf"></label>
        <button type="submit">Submit synthetic application</button></form></html>'''
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)

    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        if self.headers.get_content_type()=='application/json':
            value=json.loads(raw);payload=base64.b64decode(value.get('cv_base64',''))
            filename='standard.pdf' if payload else None
        else:
            message=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
            value={};payload=b'';filename=None
            for part in message.iter_parts():
                name=part.get_param('name',header='content-disposition')
                if name=='cv':payload=part.get_payload(decode=True);filename=part.get_filename()
                else:value[name]=part.get_content()
        observation={'receipt_id':'synthetic-'+str(len(self.server.observations)+1),
            'cv_sha256':hashlib.sha256(payload).hexdigest() if payload else None,
            'filename':filename,'fields':{k:v for k,v in value.items() if k!='cv_base64'}}
        self.server.observations.append(observation)
        if self.headers.get_content_type()=='application/json':
            body=json.dumps(observation).encode();kind='application/json'
        else:
            body=('<html><title>Synthetic submission received</title><h1>Application received</h1><p>Receipt: '+observation['receipt_id']+
                '</p><p>CV SHA256: '+str(observation['cv_sha256'])+'</p></html>').encode();kind='text/html'
        self.send_response(200);self.send_header('Content-Type',kind);self.end_headers();self.wfile.write(body)


def fixture_server():
    server=ThreadingHTTPServer(('127.0.0.1',0),FixtureATS)
    server.observations=[]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return server


@unittest.skipUnless(shutil.which('xelatex') and shutil.which('pdftoppm'),'E2E requires real document tools')
class OperationalJourneyTests(unittest.TestCase):
    def test_complete_cli_journey_and_unknown_send_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'private';inputs=Path(temp)/'inputs';inputs.mkdir()
            source=Path(__file__).resolve().parent.parent
            counter=0
            def cli(*args,data=None,success=True):
                nonlocal counter
                command=[sys.executable,'-m','fmj',*args]
                if data is not None:
                    counter+=1;path=inputs/f'input-{counter}.json';path.write_text(json.dumps(data))
                    command+=['--input',str(path)]
                result=subprocess.run(command,cwd=source,capture_output=True,text=True,timeout=60)
                self.assertEqual(0 if success else 2,result.returncode,result.stderr)
                return json.loads(result.stdout if success else result.stderr)
            config=cli('init','--workspace',str(root),'--agent','codex')['workspace']
            policy={'id':'campaign','approved':True,'markets':['example'],'languages':['en'],
                'approved_titles':['Researcher'],'hard_exclusions':{},'resource_classes':['official'],'expansion_authority':True}
            cli('record','--workspace',str(root),'--kind','campaign-policy',data=policy)
            content={'name':'Synthetic Candidate','contact':[], 'summary':'Researcher developing reproducible methods.',
                'experience':[{'title':'Researcher','organization':'Synthetic Institute','start':'2020','end':'2025',
                'bullets':['Developed a reproducible research method.','Validated the method with project collaborators.']}]}
            profile=documents.select_templates('industry')[0]
            for index,(pointer,value) in enumerate(documents.factual_fields(content,profile).items()):
                cli('record','--workspace',str(root),'--kind','fact',data={'id':f'fact-{index}','subject':'synthetic-candidate',
                    'field':pointer,'value':value,'status':'candidate_confirmed','confirmed_by':'synthetic-candidate','confirmed_at':'2026-01-01T00:00:00Z'})
            canonical=inputs/'content.json';canonical.write_text(json.dumps(content))
            approved=inputs/'profile.json';approved.write_text(json.dumps(profile))
            output=root/'resumes'/'researcher'
            built=cli('documents','build','--workspace',str(root),'--content',str(canonical),'--profile',str(approved),'--output',str(output))
            pack=cli('documents','review-pack','--bundle',str(output))
            findings=inputs/'findings.json';findings.write_text('[]')
            cli('documents','review','--bundle',str(output),'--reviewer','synthetic-independent-review-fixture',
                '--findings',str(findings),'--independent','--pages',*[page['id'] for page in pack['pages']])
            self.assertTrue(cli('documents','finalize','--bundle',str(output),'--workspace',str(root))['ready'])
            for name in ('browser','upload'):
                observation=root/'artifacts'/(name+'.json');observation.write_text(json.dumps({'adapter':'synthetic-local-ats','capability':name,'scope':'inert integration fixture'}))
                cli('capability','--workspace',str(root),'--name',name,'--adapter','synthetic-local-ats','--evidence',str(observation))
            attachment={'field':'cv','role':'cv','path':str(output/'standard.pdf'),
                'sha256':hashlib.sha256((output/'standard.pdf').read_bytes()).hexdigest(),
                'workspace_id':config['id'],'mime_type':'application/pdf'}
            bundle={'directory':str(output),'workspace_id':config['id'],'artifact_hashes':built['manifest']['artifact_hashes']}
            server=fixture_server();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            base='http://127.0.0.1:'+str(server.server_port)
            with urlopen(base+'/opportunities/1') as response:self.assertIn(b'Synthetic',response.read())
            def opportunity(index,**extra):return {'employer':'Synthetic Institute','title':'Researcher','resource_class':'official','url':base+f'/opportunities/{index}',**extra}
            first=cli('campaign','prepare','--workspace',str(root),data={'opportunity':opportunity(1,referral_available=True),
                'policy_id':'campaign','bundle':bundle,'attachments':[attachment]})
            company=first['intent']['opportunity']['company_id']
            person=cli('track','contact','--workspace',str(root),data={'channel':'email','address':'employee@example.invalid','company_id':company})
            cli('track','referral','--workspace',str(root),data={'opportunity_id':first['opportunity_id'],'contacts':[person['id']],
                'selected_contact':person['id'],'status':'selected','evidence':'Observed synthetic referral link','policy_id':'campaign'})
            actual={'fields':{},'recipient':None,'attachments':[attachment]}
            def send(operation,complete=True):
                bridge=cli('campaign','begin','--workspace',str(root),'--operation',operation['id'],data=actual)
                request=Request(base+'/apply',data=json.dumps({'opportunity_id':operation['opportunity_id'],
                    'cv_base64':base64.b64encode((output/'standard.pdf').read_bytes()).decode()}).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as response:receipt=json.load(response)
                self.assertEqual(attachment['sha256'],receipt['cv_sha256'])
                if complete:cli('campaign','complete','--workspace',str(root),'--operation',operation['id'],
                    data={'ticket':bridge['ticket'],'outcome':'submission_observed','evidence':receipt})
                return receipt
            send(first)
            unknown=cli('campaign','prepare','--workspace',str(root),data={'opportunity':opportunity(2),
                'policy_id':'campaign','bundle':bundle,'attachments':[attachment]})
            receipt=send(unknown,complete=False)
            cli('campaign','recover','--workspace',str(root))
            cli('campaign','begin','--workspace',str(root),'--operation',unknown['id'],data=actual,success=False)
            cli('campaign','receipt','--workspace',str(root),'--operation',unknown['id'],data={
                'employer':'Synthetic Institute','url':opportunity(2)['url'],'message_id':receipt['receipt_id'],'evidence':receipt})
            for event in ('interview','reply','assessment_completed','assessment_link_expired'):
                cli('campaign','observe','--workspace',str(root),'--operation',first['id'],data={'lifecycle':event,'evidence':'Synthetic '+event})
            for index in range(3,51):
                operation=cli('campaign','prepare','--workspace',str(root),data={'opportunity':opportunity(index),
                    'policy_id':'campaign','bundle':bundle,'attachments':[attachment]})
                send(operation)
            status=cli('campaign','status','--workspace',str(root))
            self.assertEqual(50,status['submission_count']);self.assertEqual(50,len(server.observations))
            self.assertEqual([50],[review['threshold'] for review in status['direction_reviews']])
            self.assertFalse(status['paused'])
            first_state=cli('campaign','show','--workspace',str(root),'--operation',first['id'])
            self.assertIn('assessment_completed',first_state['milestones']);self.assertEqual('interview',first_state['lifecycle'])
            self.assertEqual('referral',first_state['route_snapshot']['route'])
            recipient={'channel':'email','address':'researcher@example.invalid'}
            for turn in ('inbound-1','inbound-2'):
                fields={'body':'Synthetic answer to '+turn}
                operation=cli('campaign','prepare','--workspace',str(root),data={'opportunity':opportunity(1),
                    'policy_id':'campaign','action':'send_message','purpose':'reply','recipient':recipient,
                    'thread_id':'synthetic-thread','turn_id':turn,'reply_to':turn,'form_values':fields})
                bridge=cli('campaign','begin','--workspace',str(root),'--operation',operation['id'],
                    data={'fields':fields,'recipient':recipient,'attachments':[]})
                with urlopen(Request(base+'/messages',data=json.dumps(fields).encode(),headers={'Content-Type':'application/json'})) as response:
                    observation=json.load(response)
                cli('campaign','complete','--workspace',str(root),'--operation',operation['id'],
                    data={'ticket':bridge['ticket'],'outcome':'submission_observed','evidence':observation})
            self.assertEqual(2,cli('campaign','status','--workspace',str(root))['communication_count'])
            managed=Path(temp)/'managed'
            cli('init','--workspace',str(managed),'--mode','managed','--operator','operator','--owner','client','--agent','codex')
            cli('campaign','bind-client','--workspace',str(managed),'--actor','operator',data={
                'client':'client','chat_id':101,'user_id':202,'browser_profile':'synthetic-browser'})
            from fmj import telegram
            update={'update_id':1,'message':{'message_id':7,'chat':{'id':101},'from':{'id':202},'text':'Please discuss a different market with me'}}
            telegram.process_update(managed,update)
            self.assertIsNone(telegram.process_update(managed,update))
            inbox=cli('telegram','inbox','--workspace',str(managed),'--operator','operator')
            self.assertEqual(1,len(inbox));self.assertEqual(update['message']['text'],inbox[0]['body'])
            snapshot=root/'runtime'/'journey.sqlite3'
            cli('storage','backup','--workspace',str(root),'--path',str(snapshot))
            cli('storage','restore','--workspace',str(root),'--path',str(snapshot),'--apply')
            self.assertEqual(50,cli('campaign','status','--workspace',str(root))['submission_count'])
            cli('validate','--workspace',str(root))
            self.assertEqual('already_current',cli('storage','migrate','--workspace',str(root),'--apply')['status'])


if __name__=='__main__':
    if '--serve' in sys.argv:
        server=fixture_server();print(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port)}),flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:server.shutdown()
    else:unittest.main()
