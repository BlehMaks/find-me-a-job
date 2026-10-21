"""Command-line companion for the selected career agent."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from . import __version__, campaign, feedback, records, telegram, store, tracking
from .workspace import create_workspace, load_workspace, atomic_write_json, read_json, workspace_path, WorkspaceError


class UserInputError(ValueError):
    pass


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _capabilities(root):
    path=workspace_path(root,'runtime','capabilities.json')
    values=read_json(path) if path.exists() else {}
    for name,item in values.items():
        try:
            evidence=workspace_path(root,*Path(item['evidence']).relative_to(Path(root).resolve()).parts)
            if hashlib.sha256(evidence.read_bytes()).hexdigest()!=item['sha256']:item['status']='stale'
        except (OSError,ValueError,KeyError):item['status']='missing'
    return values


def doctor(root, smoke=False):
    config=load_workspace(root)
    tools={name:shutil.which(name) for name in ('codex','claude','xelatex','pdftoppm','gh')}
    try:pdf_version=importlib.metadata.version('pypdf')
    except importlib.metadata.PackageNotFoundError:pdf_version=None
    caps=_capabilities(root)
    result={'workspace_id':config['id'],'mode':config['mode'],'python':sys.version.split()[0],
            'tools':tools,'pypdf':pdf_version,'private_permissions':config['permission_status'],
            'capabilities':caps,'ready_for_intake':True,
            'document_tools_available':bool(tools['xelatex'] and tools['pdftoppm'] and pdf_version),
            'outbound_capabilities_available':all(caps.get(k,{}).get('status')=='verified' for k in ('browser','mailbox')),
            'ready_for_outbound':False,'per_operation_preflight_required':True,
            'next_action':'Use the chosen agent adapter to verify actual browser/account/upload capabilities; installation alone is not that verification.'}
    if smoke:
        from . import documents
        content={'name':'Synthetic Example','contact':[{'text':'candidate@example.invalid','url':'mailto:candidate@example.invalid'}],
                 'summary':'Synthetic installation check.', 'skills':[{'label':'Methods','items':['Research']}],
                 'experience':[{'title':'Contributor','organization':'Example Institute','start':'2020','end':'2021',
                                'bullets':['Documented a reproducible method.','Reviewed findings with collaborators.']}],
                 'education':[]}
        output=workspace_path(root,'artifacts','doctor-'+uuid.uuid4().hex)
        profile=documents.select_templates('industry')[0]
        documents.build_bundle(content,profile,output)
        report=documents.verify_bundle(output)
        result['document_smoke']={'status':report['mechanical_status'],'bundle':str(output),'independent_review':'pending'}
        result['ready_for_documents']=report['mechanical_status']=='passed'
    return result


def parser():
    p=argparse.ArgumentParser(prog='fmj',description='Private local career-assistant tools. Read AGENTS.md for the agent workflow.')
    p.add_argument('--version',action='version',version=__version__)
    commands=p.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init');init.add_argument('--workspace',required=True);init.add_argument('--mode',choices=['self-hosted','managed'],default='self-hosted')
    init.add_argument('--agent',choices=['codex','claude'],required=True);init.add_argument('--owner',default='owner');init.add_argument('--operator')
    init.add_argument('--language',default='en');init.add_argument('--timezone',default='UTC')
    init.add_argument('--feedback',choices=['unset','enabled','disabled'],default='unset');init.add_argument('--upstream')
    for name in ('doctor','run','validate'):
        q=commands.add_parser(name);q.add_argument('--workspace',required=True)
        if name=='doctor':q.add_argument('--smoke',action='store_true');q.add_argument('--json',action='store_true')
    q=commands.add_parser('record');q.add_argument('--workspace',required=True);q.add_argument('--kind',required=True);q.add_argument('--input',required=True);q.add_argument('--actor',default='owner')
    q=commands.add_parser('capability');q.add_argument('--workspace',required=True);q.add_argument('--name',choices=['browser','upload','mailbox','messaging','native'],required=True);q.add_argument('--evidence',required=True);q.add_argument('--adapter',required=True)
    storage=commands.add_parser('storage').add_subparsers(dest='action',required=True)
    for action in ('status','migrate','backup','restore'):
        q=storage.add_parser(action);q.add_argument('--workspace',required=True)
        if action in ('migrate','restore'):q.add_argument('--apply',action='store_true')
        if action in ('backup','restore'):q.add_argument('--path',required=True)
    track=commands.add_parser('track').add_subparsers(dest='action',required=True)
    for action in ('company','opportunity','contact','referral','action','list','report'):
        q=track.add_parser(action);q.add_argument('--workspace',required=True)
        if action not in ('list','report'):q.add_argument('--input',required=True)
        if action=='list':
            q.add_argument('--kind',required=True);q.add_argument('--id');q.add_argument('--limit',type=int,default=25)
    docs=commands.add_parser('documents').add_subparsers(dest='action',required=True)
    for action in ('previews','build'):
        q=docs.add_parser(action);q.add_argument('--content',required=True);q.add_argument('--family',choices=['industry','academic','portfolio'],required=True);q.add_argument('--output',required=True)
        if action=='build':q.add_argument('--variant',required=True)
    for action in ('check','finalize','review'):
        q=docs.add_parser(action);q.add_argument('--bundle',required=True)
        if action=='review':
            q.add_argument('--reviewer',required=True);q.add_argument('--findings',required=True);q.add_argument('--pages',nargs='+',required=True);q.add_argument('--independent',action='store_true')
    cs=commands.add_parser('campaign').add_subparsers(dest='action',required=True)
    for action in ('status','pause','resume','recover','screen','prepare','refresh','begin','complete','reconcile','receipt','grant','bind-client'):
        q=cs.add_parser(action);q.add_argument('--workspace',required=True);q.add_argument('--actor',default='owner')
        if action in ('screen','prepare','refresh','begin','complete','reconcile','receipt','grant','bind-client'):q.add_argument('--input',required=True)
        if action in ('refresh','begin','complete','reconcile','receipt'):q.add_argument('--operation',required=True)
        if action=='pause':q.add_argument('--reason',default='Requested pause')
    tg=commands.add_parser('telegram').add_subparsers(dest='action',required=True)
    for action in ('listen','ask'):
        q=tg.add_parser(action);q.add_argument('--workspace',required=True)
        if action=='listen':q.add_argument('--once',action='store_true')
        if action=='ask':q.add_argument('--input',required=True);q.add_argument('--operator',required=True)
    fb=commands.add_parser('feedback').add_subparsers(dest='action',required=True)
    for action in ('consent','prepare','review','review-patch','submit'):
        q=fb.add_parser(action);q.add_argument('--workspace',required=True)
        if action=='consent':q.add_argument('--enabled',choices=['yes','no'],required=True);q.add_argument('--repository',required=True);q.add_argument('--actor',required=True)
        if action=='prepare':q.add_argument('--input',required=True)
        if action in ('review','review-patch','submit'):q.add_argument('--proposal',required=True)
        if action in ('review','review-patch'):q.add_argument('--reviewer',required=True)
        if action=='review':q.add_argument('--synthetic',action='store_true')
        if action in ('review-patch','submit'):q.add_argument('--source-root')
        if action=='review-patch':q.add_argument('--base',required=True);q.add_argument('--branch',required=True)
        if action=='submit':q.add_argument('--pr-branch')
    return p


def execute(a):
    if a.command=='init':
        if a.feedback!='unset' and not a.upstream:raise UserInputError('Feedback choice requires explicit --upstream owner/repository')
        value=create_workspace(a.workspace,mode=a.mode,owner=a.owner,operator=a.operator,locale=a.language,time_zone=a.timezone,agent=a.agent)
        if a.feedback!='unset':feedback.consent(a.workspace,a.feedback=='enabled',a.upstream,a.operator if a.mode=='managed' else a.owner)
        return {'workspace':value,'feedback_choice':a.feedback,'next_action':'Read AGENTS.md with this external workspace; begin experience intake. Feedback requires explicitly enabled consent and a reviewed synthetic proposal.'}
    if a.command=='doctor':return doctor(a.workspace,a.smoke)
    if a.command=='storage':
        if a.action=='status':return {'workspace_version':load_workspace(a.workspace)['schema_version'],'database':'career.sqlite3','migration_required':load_workspace(a.workspace)['schema_version']==1}
        if a.action=='migrate':return store.migrate(a.workspace,a.apply)
        if a.action=='backup':return store.backup(a.workspace,a.path)
        if not a.apply:raise UserInputError('Restore requires --apply after inspecting the private backup')
        return store.restore(a.workspace,a.path)
    if a.command=='track':
        if a.action=='list':return tracking.query(a.workspace,a.kind,a.id,a.limit)
        if a.action=='report':return tracking.report(a.workspace)
        data=_json(a.input)
        if a.action=='opportunity':return tracking.opportunity(a.workspace,data)
        return getattr(tracking,a.action)(a.workspace,**data)
    if a.command=='run':
        config=load_workspace(a.workspace);exe=shutil.which(config['agent'])
        if not exe:raise UserInputError('Chosen agent is missing; use the official installer or install/install.sh --help')
        source=Path(__file__).resolve().parent.parent
        if not (source/'AGENTS.md').is_file():
            import sysconfig
            source=Path(sysconfig.get_path('data'))/'share/find-me-a-job'
        if not (source/'AGENTS.md').is_file():raise UserInputError('Agent workflows are missing; run from an installed checkout')
        prompt='Read AGENTS.md and the configured adapter. The explicitly selected external private workspace is '+json.dumps(str(Path(a.workspace).resolve()))+'. Resume its earliest unfinished authorized phase; do not write client data to this source directory.'
        return {'agent_exit_code':subprocess.call([exe,prompt],cwd=source)}
    if a.command=='record':return records.save_record(a.workspace,a.kind,_json(a.input),actor=a.actor)
    if a.command=='validate':
        checked=0
        for kind in ('fact','claim','evidence','answer','campaign-policy','client-binding','clarification'):
            for record in records.list_records(a.workspace,kind):
                records.validate_record(kind,record)
                if kind=='claim' and record.get('status')=='approved':records.validate_claim(a.workspace,record)
                checked+=1
        records.read_events(a.workspace)
        return {'records_checked':checked,'status':'passed'}
    if a.command=='capability':
        load_workspace(a.workspace)
        path=Path(a.evidence).resolve();root=Path(a.workspace).resolve()
        target=workspace_path(root,*path.relative_to(root).parts)
        if not target.is_file():raise UserInputError('Record actual smoke-test evidence inside the private workspace')
        data=_capabilities(root);data[a.name]={'status':'verified','evidence':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'adapter':a.adapter}
        atomic_write_json(workspace_path(root,'runtime','capabilities.json'),data)
        return {'capability':a.name,'status':'verified_by_agent_observation','scope':'Recheck account/form state before each outbound operation'}
    if a.command=='documents':
        from . import documents
        if a.action=='previews':return documents.build_previews(_json(a.content),a.family,a.output)
        if a.action=='build':
            profiles=documents.select_templates(a.family);profile=next((p for p in profiles if p['variant']==a.variant),None)
            if profile is None:raise UserInputError('Unknown structural variant')
            return documents.build_bundle(_json(a.content),profile,a.output)
        if a.action=='check':return documents.verify_bundle(a.bundle)
        if a.action=='review':return documents.record_review(a.bundle,a.reviewer,_json(a.findings),a.pages,independent=a.independent,reviewed_dimensions=['factual','vacancy_fit','visual'])
        return documents.finalize_bundle(a.bundle)
    if a.command=='campaign':
        root=a.workspace
        if a.action=='status':return campaign.status(root)
        if a.action=='pause':return campaign.set_pause(root,a.actor,a.reason)
        if a.action=='resume':return campaign.resume_campaign(root,a.actor)
        if a.action=='recover':return campaign.recover_dispatches(root,a.actor)
        data=_json(a.input)
        if a.action=='screen':return campaign.screen_opportunity(data['policy'],data['opportunity'])
        if a.action=='prepare':return campaign.create_operation(root,actor=a.actor,**data)
        if a.action=='refresh':return campaign.refresh_operation(root,a.operation,data,actor=a.actor)
        if a.action=='grant':return campaign.grant_authority(root,by=a.actor,**data)
        if a.action=='bind-client':return campaign.bind_client(root,operator=a.actor,**data)
        if a.action=='begin':
            caps=_capabilities(root)
            if caps.get('browser',{}).get('status')!='verified':raise UserInputError('Record actual browser smoke-test evidence before dispatch')
            return campaign.begin_dispatch(root,a.operation,a.actor,actual_form=data,verify_documents=lambda intent:campaign.verify_operation_documents(root,intent))
        if a.action=='complete':return campaign.complete_dispatch(root,a.operation,**data)
        if a.action=='reconcile':return campaign.reconcile_operation(root,a.operation,actor=a.actor,**data)
        if a.action=='receipt':return campaign.match_receipt(root,a.operation,data,actor=a.actor)
    if a.command=='telegram':
        if a.action=='ask':return telegram.ask(a.workspace,_json(a.input),a.operator)
        while True:
            result=telegram.poll_once(a.workspace)
            if a.once:return result
            time.sleep(1)
    if a.command=='feedback':
        if a.action=='consent':return feedback.consent(a.workspace,a.enabled=='yes',a.repository,a.actor)
        if a.action=='prepare':return feedback.prepare(a.workspace,_json(a.input))
        if a.action=='review':return feedback.review(a.workspace,a.proposal,a.reviewer,a.synthetic)
        if a.action=='review-patch':return feedback.review_patch(a.workspace,a.proposal,a.source_root,a.base,a.branch,a.reviewer)
        return feedback.submit(a.workspace,a.proposal,pr_branch=a.pr_branch,source_root=a.source_root)
    raise UserInputError('Unsupported command')


def main(argv=None):
    try:
        args=parser().parse_args(argv)
        result=execute(args)
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
        if args.command=='run':
            code=result['agent_exit_code']
            return min(255,128-code) if code<0 else min(255,code)
        if args.command=='doctor' and args.smoke and result['document_smoke']['status']!='passed':return 2
        if args.command=='documents':
            if args.action=='finalize' and not result['ready']:return 2
            if args.action=='check' and result['mechanical_status']!='passed':return 2
        return 0
    except KeyboardInterrupt:return 130
    except (ValueError,OSError,KeyError,TypeError,ImportError,sqlite3.Error) as error:
        # Do not echo exception values: they can contain private form data or credentials.
        print(json.dumps({'status':'blocked','reason_class':type(error).__name__,
                          'reason':str(error) if isinstance(error,(UserInputError,WorkspaceError,records.RecordError,campaign.CampaignBlocked,feedback.FeedbackError,telegram.TelegramError)) else 'Input, file or dependency validation failed; inspect the private source and doctor report.',
                          'next_action':'Resolve the stated blocker and resume the persisted operation; no operation was claimed successful.'}),file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
