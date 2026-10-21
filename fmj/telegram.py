"""Optional paid-client factual clarification and scoped pause control."""
import json
import os
import re
import urllib.error
import urllib.request

from . import campaign, store
from .records import load_record, save_record, append_event, identifier, _digest
from .workspace import load_workspace, locked_workspace, workspace_path, read_json, atomic_write_json, now


class TelegramError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise TelegramError("Unexpected Telegram redirect")


def request(token, method, payload):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or method not in {"getUpdates", "sendMessage"}:
        raise TelegramError("Invalid bot credential or unsupported method")
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/" + method,
                                 data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=35) as response:
            data = json.loads(response.read(2_000_000))
        if not data.get("ok"):
            raise TelegramError("Telegram rejected the operation")
        return data["result"]
    except (OSError, ValueError, urllib.error.URLError):
        raise TelegramError("Telegram operation failed; inspect private pending state, never print bot credentials") from None


def _binding(root):
    config = load_workspace(root)
    if config["mode"] != "managed":
        raise TelegramError("Telegram is available only in operator-managed mode")
    value = load_record(root, "client-binding", "client")
    if not value.get("enabled") or not value.get("confirmed"):
        raise TelegramError("Client binding is disabled or unconfirmed")
    return value


def _token(root, binding):
    ref = binding.get("bot_secret_ref")
    if not ref:
        raise TelegramError("Operator must provision a bot secret reference")
    path = workspace_path(root, "secrets", ref)
    if not path.is_file() or os.name != "nt" and path.stat().st_mode & 0o077:
        raise TelegramError("Bot credential file must be private and owner-only")
    return path.read_text().strip()


def _operator_notice(root, message, transport):
    path=workspace_path(root, "runtime", "telegram-operator.json")
    if path.exists() and read_json(path).get("chat_id"):
        binding=_binding(root)
        observation=transport(_token(root,binding), "sendMessage", {"chat_id":read_json(path)["chat_id"], "text":message})
        if not isinstance(observation,dict) or not isinstance(observation.get("message_id"),int):
            raise TelegramError("Operator notification delivery was not observed")
        return True
    else:
        append_event(root,"operator_attention_required",data={"reason":message},event_id=_digest(["operator_notice",message]))
        return False


def process_update(root, update):
    """Process locally. Returned response is sent only to the verified binding."""
    binding=_binding(root)
    message=update.get("message",{})
    campaign.authorize_client(root,message.get("chat",{}).get("id"),message.get("from",{}).get("id"))
    update_id=update.get("update_id")
    if not isinstance(update_id,int):raise TelegramError("Missing update identity")
    with locked_workspace(root):
        state=store.state(root,"telegram",{"last_update_id":-1})
        if update_id<=state["last_update_id"]:return None
        text=message.get("text","").strip();client=binding["client"]
        secret_like=bool(re.search(r"(?i)\b(password|passwd|token|secret|verification code|пароль|код)\s*[:=]|\bgh[pousr]_[A-Za-z0-9]+|\bsk-(?:proj-)?[A-Za-z0-9_-]+|^\d{4,8}$",text))
        notice=None
        request_id=None
        reply_message_id=message.get("reply_to_message",{}).get("message_id")
        questions=store.payloads(root,"runtime_state"," WHERE key LIKE 'telegram-question:%'") if reply_message_id is not None else []
        linked_question=next((q for q in questions if q.get("status")=="delivered" and q.get("message_id")==reply_message_id),None)
        if secret_like:
            reply="Do not send passwords, tokens or verification codes here. Your message was not copied into the agent journal. Contact the operator for secure credential entry."
        elif text=="/pause":
            campaign.set_pause(root,client,"Client requested a pause")
            reply="New outbound actions are paused. An in-flight action may still finish. This does not cancel the service or change billing or access."
            notice="Client paused outbound campaign actions."
        elif text=="/resume":
            campaign.resume_campaign(root,client)
            reply="Your pause has been removed. Operator pauses, unresolved handoffs and uncertain deliveries still block sending."
        elif text=="/status":
            current=campaign.status(root)
            reply=json.dumps(current,ensure_ascii=False)
        elif text.startswith("/answer "):
            parts=text.split(maxsplit=2)
            if len(parts)!=3:raise TelegramError("Use /answer question-id your factual answer")
            campaign.answer_clarification(root,parts[1],parts[2],client,update_id=update_id)
            reply="Your factual answer is saved for the agent to integrate into the confirmed record."
        elif linked_question:
            campaign.answer_clarification(root,linked_question["id"],text,client,update_id=update_id)
            reply="Your factual answer is saved for the agent to verify and update the dependent draft."
        else:
            origin=_digest([binding["client"],binding["allowed_chat_id"],binding["allowed_user_id"],message.get("message_id",update_id)])
            request_id=origin
            payload={"id":request_id,"body":text,"client":client,"chat_id":binding["allowed_chat_id"],
                "user_id":binding["allowed_user_id"],"message_id":message.get("message_id"),"update_id":update_id,"received_at":now()}
            store.connection(root).execute("INSERT OR IGNORE INTO inbox_requests VALUES(?,?,'received',?)",(request_id,origin,store.encode(payload)))
            append_event(root,"operator_service_request",actor=client,entity_id=request_id,data={"update_id":update_id},event_id=_digest(["request",origin]))
            reply="Your request is saved in the operator inbox. Campaign settings, access and service terms are handled by them."
            notice="Client request "+request_id+":\n"+text
        result={"chat_id":binding["allowed_chat_id"],"text":reply,"operator_notice":notice,"request_id":request_id}
        state.setdefault("outbox",[]).append({"update_id":update_id,"response":result,
                                            "client_delivered":False,"operator_delivered":notice is None,
                                            "intended_client":client,"intended_chat":binding["allowed_chat_id"],"intended_user":binding["allowed_user_id"]})
        state["last_update_id"]=update_id
        store.save_state(root,"telegram",state)
        return result


def ask(root, clarification, operator, *, transport=request):
    """Send a factual question once; uncertain delivery needs operator reconciliation."""
    question_id=identifier(clarification.get("id"))
    intent_key="telegram-question:"+question_id
    with locked_workspace(root):
        binding=_binding(root);config=load_workspace(root)
        if operator!=config["operator"]:
            raise TelegramError("Only the operator-controlled assistant may ask client questions")
        if clarification.get("scope",{}).get("type") not in {"personal","experience","fact"}:
            raise TelegramError("Only personal factual clarification may go directly to client")
        if clarification.get("intended_actor")!=binding["client"] or clarification.get("status")!="pending":
            raise TelegramError("Question must be pending for this bound client")
        identity={"workspace_id":config["id"],"client":binding["client"],
                  "chat_id":binding["allowed_chat_id"],"user_id":binding["allowed_user_id"]}
        question_hash=_digest(clarification)
        prior=store.state(root,intent_key)
        if prior:
            if prior["identity"]!=identity or prior["question_hash"]!=question_hash:
                raise TelegramError("Question or recipient changed; create a new question ID after operator review")
            if prior["status"]!="delivered":
                raise TelegramError("Question delivery is uncertain; reconcile it before creating a replacement")
            return {**prior["question"],"notification_status":"delivered"}
        token=_token(root,binding)
        question=save_record(root,"clarification",clarification,actor=operator)
        intent={"id":question_id,"identity":identity,"question_hash":question_hash,
                "question":question,"status":"delivery_unknown","started_at":now()}
        # Persist uncertainty before sending: a crash or timeout cannot silently replay.
        store.save_state(root,intent_key,intent)
        payload={"chat_id":identity["chat_id"],"text":question["question"]+"\nReply: /answer "+question["id"]+" your answer"}
    try:
        observation=transport(token,"sendMessage",payload)
    except (OSError,ValueError):
        raise TelegramError("Question delivery is uncertain; operator reconciliation is required") from None
    if not isinstance(observation,dict) or not isinstance(observation.get("message_id"),int):
        raise TelegramError("Question has no delivery observation; operator reconciliation is required")
    with locked_workspace(root):
        intent.update(status="delivered",message_id=observation["message_id"],delivered_at=now())
        store.save_state(root,intent_key,intent)
    return {**question,"notification_status":"delivered"}


def inbox(root, operator, request_id=None, status=None, evidence=None):
    if operator!=load_workspace(root)['operator']:
        raise TelegramError('Only the operator may inspect service requests')
    with locked_workspace(root):
        if request_id is None:
            values=store.rows(root,"SELECT status,payload FROM inbox_requests WHERE status<>'resolved' LIMIT 25")
            return [{**json.loads(v['payload']),'status':v['status']} for v in values]
        values=store.rows(root,'SELECT status,payload FROM inbox_requests WHERE id=?',(request_id,))
        if not values:raise TelegramError('Unknown service request')
        value={**json.loads(values[0]['payload']),'status':values[0]['status']}
        if status:
            if status not in {'seen','resolved'} or not evidence:
                raise TelegramError('Operator state changes require seen/resolved and observation evidence')
            if value['status']=='resolved' and status!='resolved':
                raise TelegramError('Resolved request cannot silently reopen')
            value.update(status=status,**{status+'_at':now()},evidence=evidence)
            store.connection(root).execute('UPDATE inbox_requests SET status=?,payload=? WHERE id=?',(status,store.encode(value),request_id))
        return value


def flush_outbox(root, *, transport=request):
    # Serialize notifications, but leave the ordinary writer free during network I/O.
    with locked_workspace(root,'runtime/.telegram.lock'):
        binding=_binding(root);token=_token(root,binding)
        initial=store.state(root,'telegram',{'last_update_id':-1,'outbox':[]})
        for pending in initial.get('outbox',[]):
            expected=(binding['client'],str(binding['allowed_chat_id']),str(binding['allowed_user_id']))
            if (pending.get('intended_client'),str(pending.get('intended_chat')),str(pending.get('intended_user')))!=expected:
                raise TelegramError('Pending notification belongs to another binding; operator review required')
            client_delivered=pending['client_delivered'];operator_delivered=pending['operator_delivered'];routed=False
            if not client_delivered:
                try:
                    transport(token,'sendMessage',{'chat_id':binding['allowed_chat_id'],'text':pending['response']['text']})
                    client_delivered=True
                except (OSError,ValueError):pass
            if not operator_delivered:
                try:
                    routed=_operator_notice(root,pending['response']['operator_notice'],transport)
                    # Without a configured chat the durable local inbox is the handoff.
                    operator_delivered=True
                except (OSError,ValueError):pass
            with locked_workspace(root):
                state=store.state(root,'telegram',{'last_update_id':-1,'outbox':[]})
                current=next((v for v in state.get('outbox',[]) if v['update_id']==pending['update_id']),None)
                if current:
                    current.update(client_delivered=client_delivered,operator_delivered=operator_delivered)
                request_id=pending['response'].get('request_id')
                if routed and request_id:
                    values=store.rows(root,'SELECT status,payload FROM inbox_requests WHERE id=?',(request_id,))
                    if values and values[0]['status']=='received':
                        value=json.loads(values[0]['payload']);value['routed_at']=now()
                        store.connection(root).execute("UPDATE inbox_requests SET status='routed',payload=? WHERE id=?",(store.encode(value),request_id))
                state['outbox']=[v for v in state.get('outbox',[]) if not(v['client_delivered'] and v['operator_delivered'])]
                store.save_state(root,'telegram',state)
        return {'pending_notifications':len(store.state(root,'telegram',{'outbox':[]}).get('outbox',[]))}


def poll_once(root, *, transport=request):
    binding=_binding(root);token=_token(root,binding)
    flush_outbox(root,transport=transport)
    state=store.state(root,"telegram",{"last_update_id":-1,"outbox":[]})
    updates=transport(token,"getUpdates",{"offset":state["last_update_id"]+1,"timeout":25,"allowed_updates":["message"]})
    handled=0
    for update in sorted(updates,key=lambda x:x.get("update_id",-1)):
        try:
            result=process_update(root,update)
            if result is not None:handled+=1
        except (campaign.CampaignBlocked,ValueError):
            append_event(root,"telegram_command_blocked",data={"update_id":update.get("update_id")})
            # Consume invalid/unbound updates without exposing data or repeatedly retrying them.
            number=update.get("update_id")
            if isinstance(number,int):
                with locked_workspace(root):
                    state=store.state(root,"telegram",{"last_update_id":-1,"outbox":[]})
                    state["last_update_id"]=max(state["last_update_id"],number)
                    store.save_state(root,"telegram",state)
    return {"handled":handled,**flush_outbox(root,transport=transport)}
