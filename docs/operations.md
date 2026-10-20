# Native-agent operation contract

All JSON inputs below are private workspace files. Never store real form data in source fixtures. Each subcommand has `--help`.

## Establish scope

Use `fmj record --workspace PRIVATE --kind campaign-policy --input policy.json --actor OWNER` to save a confirmed policy matching `schemas/campaign-policy.json`. Confirm titles, locations, exclusions, resource expansion and authority. The owner/operator can use `campaign grant` to delegate routine actions to an agent, bound to a policy ID/version. Actor strings record local delegation; the CLI is not a multi-user authentication server. Restrict host access separately.

After actually testing the selected browser/profile, save private evidence and run `fmj capability --workspace PRIVATE --name browser --evidence PRIVATE/runtime/browser-check.md --adapter ADAPTER`. Test upload and mailbox access separately. Capability evidence hashes detect subsequent changes. They attest the agent's observation; this command does not open a browser.

## Prepare and observe once

`campaign prepare --input intent.json` accepts `opportunity`, `policy_id`, optional document `bundle`, selected `answers`, exact `recipient`, `action`, `attachments`, `form_values` and `purpose`. Actions are `apply`, `send_message`, `connect`, `follow_up`, `submit_proposal`. Complex proposals need substantive human approval. Deduplicate by canonical employer/requisition and contact identity.

A bundle reference has this workspace's `workspace_id`, private `bundle_dir` and final `artifact_hashes` from document finalization. Document-bearing actions must pass current document gates. Document-free messages may omit a CV; actual text and exact recipients still need preflight.

Immediately before sending, observe actual `fields`, `recipient`, `cc`, `bcc`, `attachments`, attachment `constraints` and `validation_errors`. For replies with quoted history, record `quoted_history` and `new_text_position: "above_quote"`. They must match prepared intent. Recheck real tool permissions: a ticket does not override a tool-required handoff.

Call `campaign begin --operation ID --input actual-form.json --actor AGENT`. On success it returns a ticket and exact intent. Perform that one native action, then `campaign complete --operation ID --input outcome.json`; its input has `ticket`, `outcome` and observed `evidence`. Outcomes are `submission_observed`, `not_sent` or `delivery_unknown`. Never infer success from a timeout or absence of an error.

The ticket is consumed once, including an uncertain outcome. A new `begin` cannot overlap an in-flight/unknown operation. After a crash use `campaign recover`, inspect browser/mail evidence and `campaign reconcile`; never resend first. Missing matching email acknowledgement is distinct from observed delivery. `campaign receipt` records a matched acknowledgement.

## Pauses and handoffs

Every actor owns its pause. Client resume cannot clear an operator pause. Unknown deliveries and concrete credential/agreement/answer blockers remain. Save the canonical URL, completed steps, attachments and exact missing action before closing a blocked form. Close inactive task-created tabs and preserve user tabs.

Final offer, terms, appointment, withdrawal and paid decisions require the responsible person. Interview invitations trigger preparation and draft responses. A new fact or rule governs future work without rewriting historical submitted snapshots.
