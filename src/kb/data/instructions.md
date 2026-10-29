<!-- kb:begin -->
The knowledge base holds durable facts from past sessions: systems, domain rules, people, and preferences. Search it before starting a task, and again whenever a task needs a fact it may hold.
Record a durable fact when you learn it, unless the knowledge base already holds it. Subagents do not record.
- `kb recall QUERY...`: find curated sections that answer a query.
- `kb read LOCATOR...`: print the text that each locator names.
- `kb map [PATH]`: list the articles under a path.
- `kb questions [--context PATH]`: list open questions.
- `kb evidence QUERY...`: search observations, transcripts, and questions.
- `kb observe --title TITLE --body TEXT`: record one observation.
- `kb gap --title TITLE --body TEXT --context PATH`: record a question that the knowledge base cannot answer.
`kb --help` and the skills hold the details. Content policy: {content_policy}
<!-- kb:end -->
