# AI Usage Note

## How AI Helped With
- Generated the dnspython zone parsing logic, including properly handling `dns.exception.DNSException` during parsing.
- Wrote the regular expressions and string matching logic for diffing old and new zone files in `differ.py`.
- Scaffolded the GitHub Actions workflow file (`.github/workflows/dns-review.yml`) with the correct event triggers and environment variables.
- Bootstrapped the initial Pytest test suite, including the framework for parameterized testing over different zone fixtures.
- Created the JSON parsing and fallback error handling routines for interacting with the Ollama REST API in `llm_reviewer.py`.
- Formatted the markdown comment generation logic, mapping risk severities to corresponding emojis and table columns.

## What AI Got Wrong
- **Incorrect API Endpoint**: Initially, the AI suggested calling the Ollama API at `/api/generate` and passing the `format="json"` parameter incorrectly, which caused failed responses. Caught this when manual testing returned a 404, and fixed it by using the correct payload structure for Ollama.
- **dnspython Method Hallucination**: AI attempted to use a method `zone.get_records()` which does not exist in `dnspython`. Caught this during early test failures, and fixed it by correcting the loop to iterate through `zone.nodes.items()` and `rdatasets`.
- **Wrong GitHub Token Environment Variable**: The AI used `os.environ.get("GITHUB_API_TOKEN")` instead of the standard `GITHUB_TOKEN` provided by the GitHub Actions runner. Caught this when the API call to post comments failed with a 401 Unauthorized. Fixed by changing the environment variable read in `main.py`.

## Best Prompts Used
- **"Write a Python function using dnspython to parse a zone file and return a structured list of critical errors like missing SOA or NS records."** — Worked well because it explicitly constrained the AI to use `dnspython` and defined exactly what output was expected.
- **"Generate a GitHub Actions workflow that runs a Python script on pull requests, ensuring it checks out the base branch to allow git diffing."** — Excellent because it highlighted the often-missed requirement of `fetch-depth` for diffing in CI.
- **"Create a Pytest mock for the `requests.post` method that simulates a timeout error from an external API."** — Fast-tracked test writing by providing the exact syntax for `unittest.mock.patch` side effects.
- **"Write a function that formats a dictionary of DNS findings into a GitHub Markdown table with emojis for severity levels."** — Worked perfectly because it provided the specific input structure and desired output aesthetics.
- **"How do I compare two DNS MX records strictly by their wire format to avoid false positives on string formatting?"** — Yielded the brilliant solution of using `to_digestable()` instead of comparing strings.

## AI Models Used
| Task | Model Used |
|------|-----------|
| Project scaffold | Gemini Pro |
| DNS validation logic | Claude Sonnet |
| LLM integration | Gemini Pro |
| PR poster + workflow | Claude Sonnet |
| Documentation | Gemini Pro |
