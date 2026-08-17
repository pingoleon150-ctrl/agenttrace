# Collaborative repository ledger

AgentTrace writes one JSON record per analyzed GitHub repository under
`ledger/repos/github/<owner>/<repository>.json`.

Committed records allow independent installations to skip work already performed
by other contributors. A repository present in this ledger is skipped by default.
Reanalysis requires an explicit `--recheck-repository`, `--recheck-stale`, or
`--recheck-all` flag.

Submit newly generated records through pull requests. The one-file-per-repository
layout minimizes merge conflicts between contributors.
