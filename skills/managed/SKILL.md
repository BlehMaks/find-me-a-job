---
name: career-managed
description: Handle paid managed clients' personal clarifications, materials and pause/resume while leaving service resources and campaign changes to the operator.
---

# Managed operation and Telegram

Managed mode is optional; self-hosted users talk directly to their agent and need no Telegram bot. The operator provisions an external private client directory, account/session resources and initial communication. The agent may configure remaining environment only within granted authority.

Bind each workspace to its operator, client, separate browser profile and authenticated channel user/chat IDs. Verify bindings before reading records, returning material or changing pause state. A directory is organization, not a sandbox: host permissions, sessions, tokens and agent context must prevent cross-client access. Do not claim hard multi-tenant isolation from folders alone.

The operator introduces the channel and controls service/campaign changes, provisioning, access, pricing, billing and complaints. The agent can ask the bound client personal factual questions with minimal context and clear options, then record scoped confirmation. No secrets/codes/documents with unnecessary sensitive content in chat. Do not expose another client's questions or materials.

Maintain pending/answered/superseded/operator-required clarification state with update identity and linked fact/operation. Telegram redelivery must not apply an answer twice. Lost acknowledgements require reconciliation, not duplicate questions or sends. A response updates only its question scope; it does not silently grant new campaign permissions.

Allow authenticated status and read-only material/journal access for the client's own workspace. Review exports for credentials and third-party private content. Resource requests, settings, cost and access changes route to the operator.

`/pause` adds a client-owned pause, stops new outbound actions and notifies the operator. An in-flight operation may finish; reconcile once. Pause is not cancellation, refund or access revocation. `/resume` removes only the client's own pause after recovery checks. Operator pauses, mandatory handoffs and uncertain delivery remain. Operator decisions and access changes are never inferred from client silence.

Before every outbound application/message recheck effective pauses and authority under the runtime writer lock. A queued draft is not permission to send after a pause. Continue permitted research/preparation when paused, preserving progress for a controlled restart.
