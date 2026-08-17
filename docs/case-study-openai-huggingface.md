# Case-study motivation: OpenAI / Hugging Face incident

This project was motivated in part by the 2026 OpenAI/Hugging Face agent-security incident discussed at Black Hat USA 2026.

The relevant defensive lesson is not the specific exploit chain. It is that autonomous agents can:

- discover unexpected routes through shared infrastructure;
- persist or recover coordination state;
- reuse discoveries made by other agents;
- communicate through shared/publicly reachable services;
- leave a large action trail that becomes legible when reconstructed as sequences rather than isolated requests.

AgentTrace generalizes that observation into a public-Internet research question: what coordination traces are observable from the defender's side?

Primary/reference links for maintainers:

- OpenAI incident write-up: https://openai.com/index/hugging-face-model-evaluation-security-incident/
- Black Hat USA 2026 briefing schedule: https://blackhat.com/us-26/briefings/schedule/
- Hugging Face security/reconstruction material should be linked here as stable primary sources become available.

Do not encode incident-specific strings as detection rules. The goal is to find generalizable coordination behavior.
