# Threat model and research boundaries

## In scope

- Passive analysis of public GitHub artifacts and other explicitly public datasets.
- Detection of coordination patterns between pseudonymous public actors.
- Statistical, temporal, graph, and artifact analysis.
- Controlled synthetic multi-agent simulations for evaluation.

## Out of scope

- Credential theft or authentication bypass.
- Scraping behind login/access controls without authorization.
- Exploitation of discovered vulnerabilities.
- Executing untrusted payloads from public repositories.
- Interacting with or attempting to command suspected agents.
- Deanonymizing pseudonymous users into real-world identities.
- Publishing sensitive personal information.

## Adversaries

Potentially interesting behaviors include autonomous agents that intentionally or accidentally communicate through public infrastructure, and benign automated systems that resemble them.

The principal engineering threat to AgentTrace is false attribution. The system therefore uses evidence bundles and multi-signal thresholds rather than binary labels.
