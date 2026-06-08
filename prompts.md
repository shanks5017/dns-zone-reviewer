# Prompts Used During Development

## Phase 1 — Project Setup
**Model:** Gemini Pro  
**Prompt:** Create a Python project scaffold for a DNS Zone Reviewer tool. Include a `pyproject.toml`, `requirements.txt` with `dnspython` and `pytest`, and a GitHub Actions workflow `.github/workflows/dns-review.yml` that runs on pull requests to diff and review `.txt` files in a `zones/` directory.
**Result:** Created project scaffold with GitHub Actions workflow.

## Phase 2 — DNS Validation
**Model:** Claude Sonnet  
**Prompt:** Write a Python module using `dnspython` that parses a DNS zone file and returns a list of findings. It should strictly enforce RFC rules and flag missing SOA/NS records as CRITICAL, and TTLs below 300 seconds for A/MX records as WARNING. Use a structured TypedDict for the findings.
**Result:** Generated the `validator.py` logic with rigorous checks for wildcards, CNAMEs at apex, missing NS/SOA, and TTL limits.

## Phase 3 — LLM Integration
**Model:** Gemini Pro  
**Prompt:** Write a Python function that takes a git diff and a list of DNS validation findings, and sends them to a local Ollama instance running `llama3.2`. The prompt should ask the LLM to assess the risk, provide a summary, and return the response strictly as a JSON object with specific fields like `risk_level` and `safe_to_merge`. Include a fallback mechanism if Ollama is unreachable.
**Result:** Created `llm_reviewer.py` with the Ollama integration and robust JSON fallback handling.

## Phase 4 — GitHub PR Poster
**Model:** Claude Sonnet  
**Prompt:** Write a Python script to post a markdown comment to a GitHub Pull Request using the GitHub REST API. The script should read `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and `PR_NUMBER` from environment variables, search for any existing bot comment to update or delete it, and then post the new comment.
**Result:** Implemented `github_poster.py` with secure API interactions and previous-comment deletion logic.

## Phase 5 — Documentation
**Model:** Gemini Pro  
**Prompt:** Generate a comprehensive production-grade README.md, an AI usage note detailing what the AI helped with and what it got wrong, and a GitHub Pull Request template with a pre-merge checklist for DNS changes.
**Result:** Finalized all project documentation, README formatting, and submission polish artifacts.
