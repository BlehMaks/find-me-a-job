# Private operational memory

Each person has one external private workspace and `career.sqlite3`. Companies,
verified group relationships, opportunities and URL/requisition aliases,
applications, preparation revisions, send attempts, documents, contacts,
conversation turns, observations, receipts, next actions and client requests are
linked by stable IDs. Knowledge facts/claims keep their immutable version files.
Passwords and verification codes belong outside operational records.

Documents may occupy several directories **inside the selected workspace**.
The database records their paths, hashes, selected variant and evidence versions.
There is no requirement to put all outputs into one directory. Never move one
client's material into another workspace to satisfy a path check.

## Minimal recording protocol

1. Read `campaign status` on resume: current obligations and uncertain sends first.
2. Capture a discovery with `track opportunity`; company registration and aliases
   are resolved automatically. Register verified company aliases/groups with
   `track company`, and contacts with `track contact`.
3. Use normal prepare/begin/complete/receipt/observe commands. They persist their
   own effects, IDs and observations. Supply actual external evidence once.
4. Regenerate summaries with `track report` or bounded `track list`. Do not write
   a second narrative ledger, repeat the full intent in events, or start another
   model to recount actions. No model helper is required for bookkeeping.

Example queries (substitute the explicitly selected private workspace):

```sh
fmj campaign status --workspace PRIVATE
fmj campaign show --workspace PRIVATE --operation ID
fmj track list --workspace PRIVATE --kind companies
fmj track list --workspace PRIVATE --kind applications
fmj track list --workspace PRIVATE --kind opportunities --limit 25
fmj track list --workspace PRIVATE --kind events --id OPERATION_ID
fmj track report --workspace PRIVATE
```

Mutations accept private JSON using `--input`; each command's `--help` describes
its options. `track action` accepts kind, owner, operation_id, optional aware
due_at/deadline_source, blocker and evidence. Completion/cancellation requires
evidence. `campaign observe` accepts lifecycle and evidence, optional occurred_at,
due_at/deadline_source and owner. Runtime fills observation time and creates
the associated next action. Completion, employer receipt and evaluation of an
assessment are separate. Missing mail or an expired link cannot undo completion.
Use a stable `assessment_id` when a process has multiple tests/rounds; completing
one test must not hide a different newly assigned assessment.

## Referral before application

For an appropriate industry opportunity, record `referral_available: true`.
Preparation starts a finite wait while the agent finds relevant employees and
prepares the CV. Referral messages use `purpose: referral`, explicit conversation
turns and registered contacts. `track referral` records contact IDs and the chosen
route; select a single observed referral before applying. Continue other work.

Campaign `referral_policy` defaults to at most three parallel contacts, three
Monday–Friday business days in the workspace timezone, and a documented direct
exception for verified publication within 48 hours. There is no holiday calendar.
An observed deadline caps waiting. Discovery today does not prove publication
today. Verified employer-specific rules and a documented lack of suitable
contacts can justify a direct route. The application keeps its route snapshot;
a late referral link never creates another application. Scientific host outreach
is a separate profession-specific route, not an industry referral wait.

Preserve broad search and approved expansion. Before declaring a significant
skill gap, inspect current knowledge; `track evidence` accepts `terms` and returns
references or unknown/confirmed absence. Text matches do not prove proficiency.
After each 50 unique observed new-campaign applications, runtime creates one
nonblocking direction review. Discuss relevance and unexpected opportunities;
do not narrow automatically. `track review` records the responsible person's
response. Imported history, messages and repeated receipts add no review count.

## Migration, backup and recovery

```sh
fmj storage migrate --workspace PRIVATE
fmj storage migrate --workspace PRIVATE --apply
fmj storage backup --workspace PRIVATE --path PRIVATE/runtime/snapshot.sqlite3
fmj storage restore --workspace PRIVATE --path PRIVATE/runtime/snapshot.sqlite3 --apply
```

Inspection validates old events/intents before cutover. Migration takes exclusive
writer/dispatch locks, saves original sources, verifies linked counts and retains
source hashes. An interrupted migration blocks work until explicitly resumed.
Valid delivery observations override stale ready snapshots. Old JSON journals
remain archival evidence; older runtimes cannot write to version-2 workspaces.

Backups use SQLite's consistent backup API. A database backup alone does not copy
the referenced knowledge, PDF, source, image or original evidence files: preserve
the complete private workspace alongside it. Restore validates schema, binding,
event hashes, intents and foreign keys; saves current SQL state; and refuses to
erase later observed/uncertain sends. Recovery after losing the database creates
an owner/operator pause: reconcile external actions since backup before resuming.

Reports contain observed records, not guaranteed hiring conversion. Receipt
coverage, source/route, attained milestones and company concentration are
separate. Silence is pending; incomplete observation windows and unrecorded
effort remain unknown. Keep all databases, backups and exports outside Git.
