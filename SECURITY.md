# Security

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/zenHeart/judge-repo/security/advisories/new). Please do not open a public issue.

judge-repo uses your existing `gh` login and never reads or stores the token itself. README content from judged repositories is untrusted; short status excerpts and the repository description reach the agent after control and invisible characters are removed, and the skill tells it to ignore instructions inside them. Text from judged repositories is not passed through a shell.
