# Find Me a Job

Tools and agent workflows for evidence-based career applications.

## Public source boundary

This repository contains reviewed product source and synthetic examples only.
Keep candidate documents, account details, correspondence, browser state,
application records, interview notes, experiments and development plans outside
this checkout. An ignored file is still a local file; ignoring it does not make
it safe to share, upload or include in an archive.

Enable the local commit check after cloning:

```sh
git config --local core.hooksPath .githooks
python3 scripts/check_public_tree.py
```

The check inspects the entire staged tree, including files added with force.
Unknown paths, links, binary content and common sensitive-data markers fail
closed. Extend the explicit path list and ignore rules only for reviewed product
files. Use reserved example domains for synthetic email addresses.

This is an accidental-disclosure guard, not a complete anonymization detector.
Names, work histories and other personal facts still require human review.
Hooks are local and bypassable; run the check separately before publication.
The check does not inspect earlier commits, Git identities, tags or configuration.
Start with clean history and choose a deliberate public commit identity.
Private data may be sent to a chosen model provider during agent use; local file
storage does not imply local model inference.
