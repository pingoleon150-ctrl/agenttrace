# Security policy

AgentTrace analyzes untrusted public content. Treat every collected string, URL, code block, archive record, and repository as hostile input.

## Never

- execute collected code;
- automatically clone and run candidate repositories;
- follow arbitrary URLs with privileged credentials;
- deserialize unsafe object formats;
- bypass platform authentication or rate limits.

## Reporting vulnerabilities

Please report vulnerabilities privately to the repository maintainers rather than opening a public issue containing exploit details.
