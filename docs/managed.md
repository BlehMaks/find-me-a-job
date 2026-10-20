# Operator-managed workspaces

Provision each client outside source with a distinct workspace, browser session and agent context. Restrict host accounts/permissions. A directory is not an operating-system sandbox. Self-hosted users do not need Telegram.

1. Initialize managed mode with an explicit owner/client and operator. Introduce service data transfers and the factual-question channel directly. The operator retains service, access, resources, campaign and commercial management.
2. Create a Telegram bot through Telegram's official process. Store its credential in an owner-only file under the workspace's `secrets/`, referenced by a simple handle such as `bot-token`. Never put tokens in command arguments, prompts, source, logs or chat. Review native Windows ACLs separately.
3. Verify numeric Telegram user/chat IDs and browser profile. `campaign bind-client` takes JSON with `client`, `chat_id`, `user_id`, `browser_profile` and `bot_secret_ref`. Client identity is immutable; pending notifications stay bound to their intended identity.
4. Optionally create private `runtime/telegram-operator.json` with the operator's verified `chat_id`. Otherwise the journal records operator attention. Use one bot/poller per workspace to avoid competing Telegram offsets.
5. Run `fmj telegram listen --workspace PRIVATE --once` for an authorized check, then `listen` for polling. Use `telegram ask --operator OPERATOR --input question.json` only for factual clarification matching `schemas/clarification.json` and the bound client. Inspect pending questions before retrying uncertain notification delivery.

Client commands: `/answer QUESTION_ID factual answer`, `/status`, `/pause`, `/resume`. Other service/campaign text is classified and routed to the operator without copying arbitrary text into journals; the operator continues that conversation directly. Do not send passwords or codes to the bot. The agent can read the client's materials with `campaign.read_material`; review exports for unnecessary third-party information and secrets.

Pause stops new outbound actions and notifies the operator. An in-flight action may finish and needs reconciliation. Resume clears only the client's pause. Neither command cancels service, promises refunds, changes campaign scope or revokes access. Local actor labels do not protect against an administrator who controls the host.
