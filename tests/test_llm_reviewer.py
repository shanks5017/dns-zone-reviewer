"""
test_llm_reviewer.py - Pytest test suite for src/llm_reviewer.py
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
import requests

from llm_reviewer import analyze_with_llm, _get_fallback_response

# Sample data
SAMPLE_DIFF = "+++ b/zones/example.com.txt\n- www IN A 1.2.3.4\n+ www IN A 5.6.7.8"
SAMPLE_FINDINGS = [
    {
        "severity": "WARNING",
        "record_type": "A",
        "description": "TTL too low",
        "record": "www 60 IN A 5.6.7.8"
    }
]

VALID_LLM_RESPONSE = {
    "summary": "Modified A record for www.",
    "risk_level": "LOW",
    "llm_findings": [
        {
            "severity": "INFO",
            "title": "A Record Changed",
            "description": "IP changed from 1.2.3.4 to 5.6.7.8",
            "recommendation": "Verify the new IP is correct."
        }
    ],
    "safe_to_merge": True,
    "reviewer_note": "Looks good."
}

@patch('llm_reviewer.requests.post')
def test_successful_llm_response(mock_post: MagicMock) -> None:
    """Test that a successful Ollama response is parsed correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": json.dumps(VALID_LLM_RESPONSE)
    }
    mock_post.return_value = mock_response
    
    result = analyze_with_llm(SAMPLE_DIFF, SAMPLE_FINDINGS, "zones/example.com.txt")
    
    assert result["llm_available"] is True
    assert result["model_used"] == "llama3.2"
    assert result["risk_level"] == "LOW"
    assert len(result["llm_findings"]) == 1
    assert result["llm_findings"][0]["title"] == "A Record Changed"

@patch('llm_reviewer.requests.post')
def test_fallback_unreachable(mock_post: MagicMock) -> None:
    """Test that when Ollama is unreachable, it gracefully falls back."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
    
    result = analyze_with_llm(SAMPLE_DIFF, SAMPLE_FINDINGS, "zones/example.com.txt")
    
    assert result["llm_available"] is False
    assert result["risk_level"] == "MEDIUM" # Because of WARNING finding in SAMPLE_FINDINGS
    assert result["safe_to_merge"] is True
    assert len(result["llm_findings"]) == 1
    assert result["llm_findings"][0]["severity"] == "WARNING"
    assert "LLM review skipped" in result["reviewer_note"]

@patch('llm_reviewer.requests.post')
def test_fallback_invalid_json(mock_post: MagicMock) -> None:
    """Test that invalid JSON from the LLM falls back to validator findings."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "This is not valid JSON."
    }
    mock_post.return_value = mock_response
    
    result = analyze_with_llm(SAMPLE_DIFF, SAMPLE_FINDINGS, "zones/example.com.txt")
    
    assert result["llm_available"] is True
    assert result["model_used"] == "llama3.2"
    assert result["risk_level"] == "MEDIUM"
    assert len(result["llm_findings"]) == 1

def test_fallback_fields_present() -> None:
    """Test that the fallback response contains all required fields."""
    result = _get_fallback_response(SAMPLE_FINDINGS)
    
    required_fields = [
        "llm_available", "model_used", "summary", 
        "risk_level", "llm_findings", "safe_to_merge", "reviewer_note"
    ]
    for field in required_fields:
        assert field in result
