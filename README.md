# 🔍 DNS Zone Reviewer — AI-Powered GitHub PR Bot

## What It Does
The DNS Zone Reviewer is an automated bot that reviews changes to DNS zone files during the pull request process. It instantly catches potentially dangerous misconfigurations, like missing records or very short cache times, and provides a clear risk assessment using AI. This helps teams catch mistakes before they cause downtime, explaining the technical risks in plain English directly on the PR.

## Architecture
```
PR Opened 
   │
   ▼
GitHub Action Triggers 
   │
   ▼
Zone Differ (identifies changed files & exact line diffs)
   │
   ▼
dnspython Validator (runs strict RFC checks)
   │
   ▼
Ollama LLM Risk Flagger (analyzes context & assigns risk level)
   │
   ▼
GitHub PR Comment Posted (outputs findings & merge recommendations)
```

## Tech Stack
| Component | Technology |
|-----------|-----------|
| CI/CD | GitHub Actions |
| DNS Validation | Python dnspython |
| LLM Risk Analysis | Groq API (llama3-8b-8192) |
| PR Integration | GitHub REST API |
| Testing | Pytest (50 tests) |
| Language | Python 3.11 |

## Setup Instructions
1. Clone the repo
   ```bash
   git clone https://github.com/shanks5017/dns-zone-reviewer.git
   cd dns-zone-reviewer
   ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Set GROQ_API_KEY environment variable
   ```bash
   export GROQ_API_KEY="your_groq_api_key"
   ```
4. Set environment variables
   ```bash
   export GITHUB_TOKEN="your_personal_access_token"
   export GITHUB_REPOSITORY="your_user/your_repo"
   export PR_NUMBER="1"
   ```
5. Run locally
   ```bash
   python src/main.py
   ```

## How to Add to Your Own Repo
To use this bot in another repository, copy the `.github/workflows/dns-review.yml` file into your repository. Ensure your zone files are stored in the `zones/` directory and use the `.txt` extension. The action will run automatically when a PR is opened or updated.

## Running Tests
Run all 50 tests using:
```bash
python -m pytest -v
```

## Environment Variables
| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | A token with read/write access to pull requests for posting comments. Automatically provided by GitHub Actions in `secrets.GITHUB_TOKEN`. |
| `GITHUB_REPOSITORY` | The name of the repository in the format owner/repo. Used by the GitHub REST API. |
| `PR_NUMBER` | The ID number of the pull request to post the comment to. Automatically available in GitHub Actions. |
| `GITHUB_BASE_REF` | The base branch the PR is targeting (e.g., main). Used to diff the changes. |

## Sample Output
## 🔍 DNS Zone Review Bot — `zones/risky_zone.txt`

### 📊 Risk Assessment
| Field | Value |
|-------|-------|
| Risk Level | 🔴 CRITICAL |
| Safe to Merge | ❌ No |
| LLM Model | llama3.2 |

### 🚨 Findings
❌ CRITICAL — Wildcard Record Detected
⚠️ WARNING — Low TTL on MX Record

### 💬 Reviewer Note
Do not merge. Review wildcard record immediately.

## Assumptions & Limitations
- Ollama must be running locally or in CI
- Only supports `zones/*.txt` file format
- LLM analysis may vary — validator findings are deterministic

## Team
Team Name: DNS Defenders
Members: User 1, User 2, User 3, User 4
