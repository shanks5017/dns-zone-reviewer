"""
llm_reviewer.py - LLM Risk Flagger for DNS Zone Reviewer using Groq.

Analyzes DNS zone file diffs and validator findings using Groq LLM
to provide human-readable risk assessments and summaries.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Mapping, Sequence

import requests

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "llama-3.1-8b-instant"
TIMEOUT_SECONDS = 60

def _get_fallback_response(
    validator_findings: Sequence[Mapping[str, Any]], 
    llm_available: bool = False, 
    model_used: str = "none"
) -> Dict[str, Any]:
    """
    Generate a structured fallback response using only the validator findings.

    Args:
        validator_findings (Sequence): Findings from the validator.
        llm_available (bool): Whether the LLM was reachable.
        model_used (str): The model that was attempted.

    Returns:
        dict: A structured fallback response conforming to the expected LLM output.
    """
    risk_level = "CLEAN"
    safe_to_merge = True
    llm_findings: List[Dict[str, Any]] = []
    
    for f in validator_findings:
        sev = str(f.get("severity", "INFO"))
        if sev == "CRITICAL":
            risk_level = "CRITICAL"
            safe_to_merge = False
        elif sev == "WARNING" and risk_level not in ["CRITICAL", "HIGH"]:
            risk_level = "MEDIUM"
            
        llm_findings.append({
            "severity": sev,
            "title": f"Validator finding: {f.get('record_type', 'Unknown')} record issue",
            "description": str(f.get("description", "No description provided")),
            "recommendation": "Review the specific DNS record indicated by the validator."
        })
        
    return {
        "llm_available": llm_available,
        "model_used": model_used,
        "summary": "LLM review was skipped or failed. Falling back to validator findings.",
        "risk_level": risk_level,
        "llm_findings": llm_findings,
        "safe_to_merge": safe_to_merge,
        "reviewer_note": "⚠️ LLM review skipped - running validator results only"
    }

def analyze_with_llm(diff: str, validator_findings: Sequence[Mapping[str, Any]], filename: str) -> Dict[str, Any]:
    """
    Analyze the DNS zone file diff and validator findings using a local Ollama LLM.

    Args:
        diff (str): Unified diff of the zone file.
        validator_findings (list): Findings from the DNS syntax validator.
        filename (str): Name of the zone file.

    Returns:
        dict: A structured dictionary containing the LLM's analysis and risk assessment.
    """
    validator_findings_json = json.dumps(validator_findings, indent=2)
    
    # Parse the prompt into system and user for Groq messages array
    # The prompt consists of SYSTEM: ... USER: ...
    # We will just split it simple or define it explicitly:
    system_prompt = """You are a DNS security expert reviewing DNS zone file changes 
in a GitHub Pull Request. Your job is to identify risky or 
dangerous DNS changes that could cause outages, security 
vulnerabilities, or email delivery failures.

Always respond in valid JSON only. No markdown. No explanation 
outside the JSON."""

    user_prompt = f"""I need you to review this DNS zone file change.

Filename: {filename}

Git Diff:
{diff}

Validator findings already detected:
{validator_findings_json}

Analyze the diff and return a JSON response in exactly 
this format:
{{
  "summary": "one sentence summary of what changed",
  "risk_level": "CRITICAL / HIGH / MEDIUM / LOW / CLEAN",
  "llm_findings": [
    {{
      "severity": "CRITICAL/WARNING/INFO",
      "title": "short title",
      "description": "detailed human readable explanation of why this is risky",
      "recommendation": "what the reviewer should do"
    }}
  ],
  "safe_to_merge": true/false,
  "reviewer_note": "final note to the human reviewer"
}}

Focus especially on:
- Wildcard DNS records (massive security risk)
- TTL below 300 seconds (instability risk)  
- MX record modifications (email delivery risk)
- NS record deletions (domain hijack risk)
- SOA serial going backwards (DNS sync failure)
- CNAME at zone apex (breaks DNS resolution)
- Any record deletion without replacement

Return ONLY the JSON. No markdown fences. No explanation."""

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY environment variable not set.")
        return _get_fallback_response(validator_findings, llm_available=False, model_used="none")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": PRIMARY_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(GROQ_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
        if response.status_code == 200:
            result_text = response.json()["choices"][0]["message"]["content"]
            
            # Strip markdown fences if the LLM ignored instructions
            result_text = result_text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            elif result_text.startswith("```"):
                result_text = result_text[3:]
            
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            result_text = result_text.strip()
            
            try:
                parsed_result = json.loads(result_text)
                parsed_result["llm_available"] = True
                parsed_result["model_used"] = PRIMARY_MODEL
                return parsed_result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM JSON response for model {PRIMARY_MODEL}: {e}")
                return _get_fallback_response(validator_findings, llm_available=True, model_used=PRIMARY_MODEL)
        else:
            logger.error(f"Groq API returned status {response.status_code}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to reach Groq API: {e}")
        
    return _get_fallback_response(validator_findings, llm_available=False, model_used="none")
