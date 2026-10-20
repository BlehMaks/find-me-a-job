"""Optional paid-client factual clarification and scoped pause control."""
import json
import os
import re
import urllib.error
import urllib.request

from . import campaign
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
        transport(_token(root,binding), "sendMessage", {"chat_id":read_json(path)["chat_id"], "text":message})
    else:
        append_event(root,"operator_attention_required",data={"reason":message})


def process_update(root, update):
    """Process locally. Returned response is sent only to the verified binding."""
    binding=_binding(root)
    message=update.get("message",{})
    campaign.authorize_client(root,message.get("chat",{}).get("id"),message.get("from",{}).get("id"))
    update_id=update.get("update_id")
    if not isinstance(update_id,int):raise TelegramError("Missing update identity")
    state_path=workspace_path(root,"runtime","telegram-state.json")
    with locked_workspace(root):
        state=read_json(state_path) if state_path.exists() else {"last_update_id":-1}
        if update_id<=state["last_update_id"]:return None
        text=message.get("text","").strip();client=binding["client"]
        secret_like=bool(re.search(r"(?i)\b(password|passwd|token|secret|verification code)\s*[:=]",text))
        notice=None
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
        else:
            append_event(root,"operator_service_request",actor=client,data={"classification":"service_or_campaign_request","update_id":update_id})
            reply="Your request has been routed to the operator. Campaign settings, access and service terms are handled by them."
            notice="Client has a service/campaign request in the private journal."
        result={"chat_id":binding["allowed_chat_id"],"text":reply,"operator_notice":notice}
        state.setdefault("outbox",[]).append({"update_id":update_id,"response":result,
                                            "client_delivered":False,"operator_delivered":notice is None,
                                            "intended_client":client,"intended_chat":binding["allowed_chat_id"],"intended_user":binding["allowed_user_id"]})
        state["last_update_id"]=update_id
        atomic_write_json(state_path,state)
        return result


def ask(root, clarification, operator, *, transport=request):
    """Send a factual question once; uncertain delivery needs operator reconciliation."""
    question_id=identifier(clarification.get("id"))
    intent_path=workspace_path(root,"runtime","telegram-questions",question_id+".json")
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
        if intent_path.exists():
            prior=read_json(intent_path)
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
        atomic_write_json(intent_path,intent)
        payload={"chat_id":identity["chat_id"],"text":question["question"]+"\nReply: /answer "+question["id"]+" your answer"}
    try:
        observation=transport(token,"sendMessage",payload)
    except (OSError,ValueError):
        raise TelegramError("Question delivery is uncertain; operator reconciliation is required") from None
    if not isinstance(observation,dict) or not isinstance(observation.get("message_id"),int):
        raise TelegramError("Question has no delivery observation; operator reconciliation is required")
    with locked_workspace(root):
        intent.update(status="delivered",message_id=observation["message_id"],delivered_at=now())
        atomic_write_json(intent_path,intent)
    return {**question,"notification_status":"delivered"}


def flush_outbox(root, *, transport=request):
    binding=_binding(root);token=_token(root,binding)
    state_path=workspace_path(root,"runtime","telegram-state.json")
    with locked_workspace(root):
        state=read_json(state_path) if state_path.exists() else {"last_update_id":-1,"outbox":[]}
        for item in state.get("outbox",[]):
            if (item.get("intended_client"),str(item.get("intended_chat")),str(item.get("intended_user"))) != (binding["client"],str(binding["allowed_chat_id"]),str(binding["allowed_user_id"])):
                raise TelegramError("Pending notification belongs to another binding; operator review required")
            if not item["client_delivered"]:
                try:
                    response=item["response"]
                    transport(token,"sendMessage",{"chat_id":binding["allowed_chat_id"],"text":response["text"]})
                    item["client_delivered"]=True
                except TelegramError:
                    pass
            # Notify the operator independently, even if the client's reply failed.
            if not item["operator_delivered"]:
                try:
                    _operator_notice(root,item["response"]["operator_notice"],transport)
                    item["operator_delivered"]=True
                except TelegramError:
                    pass
            atomic_write_json(state_path,state)
        state["outbox"]=[item for item in state.get("outbox",[]) if not(item["client_delivered"] and item["operator_delivered"])]
        atomic_write_json(state_path,state)
        return {"pending_notifications":len(state["outbox"])}


def poll_once(root, *, transport=request):
    binding=_binding(root);token=_token(root,binding)
    flush_outbox(root,transport=transport)
    state_path=workspace_path(root,"runtime","telegram-state.json")
    state=read_json(state_path) if state_path.exists() else {"last_update_id":-1,"outbox":[]}
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
                    state=read_json(state_path) if state_path.exists() else {"last_update_id":-1,"outbox":[]}
                    state["last_update_id"]=max(state["last_update_id"],number)
                    atomic_write_json(state_path,state)
    return {"handled":handled,**flush_outbox(root,transport=transport)}
