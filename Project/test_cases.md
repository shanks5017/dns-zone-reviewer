# Test Cases — DNS Zone Reviewer Bot

## Summary
| Total Tests | Passed | Failed | Coverage |
|-------------|--------|--------|----------|
| 50 | 50 | 0 | Core pipeline |

## Test Suite 1 — DNS Validator (test_validator.py)
| Test Name | What it tests | Expected Result |
|-----------|---------------|-----------------|
| **TestValidCleanZone** | | |
| `test_valid_returns_true` | Validating a clean zone file | `valid=True` returned |
| `test_no_errors` | Clean zone file parse errors | `errors=[]` returned |
| `test_no_findings` | Clean zone file findings | `findings=[]` returned |
| `test_minimal_valid_zone` | Minimal valid zone with SOA, NS, A | `valid=True` and zero findings |
| **TestWildcardRecord** | | |
| `test_wildcard_inline_is_critical` | Zone with a wildcard A record | At least one CRITICAL finding |
| `test_wildcard_finding_record_type` | CRITICAL finding references correct type | Finding references 'A' record and 'wildcard' |
| `test_test_domain_has_wildcard_critical`| Canonical test domain with wildcard | CRITICAL finding for wildcard |
| **TestMissingNS** | | |
| `test_missing_ns_is_critical` | Zone missing an NS record | CRITICAL finding for 'NS' |
| `test_test_domain_missing_ns_critical` | Canonical test domain missing NS | CRITICAL finding for 'NS' |
| **TestMissingSOA** | | |
| `test_missing_soa_is_critical` | Zone missing an SOA record | CRITICAL finding for 'SOA' |
| **TestLowTTLMX** | | |
| `test_low_ttl_mx_inline_is_warning` | MX record with TTL < 300 | WARNING finding for 'MX' |
| `test_low_ttl_mx_description_mentions_ttl` | WARNING description text | Description includes TTL value '60' |
| `test_test_domain_low_ttl_mx_warning` | Canonical test domain low-TTL MX | WARNING finding for 'MX' |
| `test_normal_ttl_mx_no_warning` | MX record with normal TTL | No TTL warning for 'MX' |
| **TestLowTTLA** | | |
| `test_low_ttl_a_is_warning` | A record with TTL < 300 | WARNING finding for 'A' |
| **TestInvalidZone** | | |
| `test_invalid_zone_returns_valid_false` | Garbled/corrupted zone file | `valid=False` returned |
| `test_invalid_zone_has_errors` | Invalid zone file error messages | Errors list is not empty |
| `test_invalid_zone_has_no_findings` | Invalid zone file findings list | `findings=[]` returned |
| `test_empty_zone_missing_required_records`| Empty zone file missing SOA/NS | CRITICAL findings for 'SOA' and 'NS' |
| **TestDifferentialChecks** | | |
| `test_soa_serial_regression_is_critical` | Decreasing SOA serial number | CRITICAL finding for 'SOA' |
| `test_new_txt_record_produces_info` | Adding a new TXT record | INFO finding for 'TXT' |
| `test_ttl_change_produces_info` | Changing an A record's TTL | INFO finding mentioning 'ttl' |

## Test Suite 2 — LLM Reviewer (test_llm_reviewer.py)
| Test Name | What it tests | Expected Result |
|-----------|---------------|-----------------|
| `test_successful_llm_response` | Successful LLM response from API | Parsed response matches expected valid LLM data |
| `test_fallback_unreachable` | Graceful fallback when API is unreachable | `llm_available=False`, `safe_to_merge=True`, proper fallback findings |
| `test_fallback_invalid_json` | Fallback when LLM returns invalid JSON | `llm_available=True`, `risk_level="MEDIUM"`, parsed fallback findings |
| `test_fallback_fields_present` | Fallback response format completeness | All required fields present in the output |

## Test Suite 3 — GitHub Poster (test_github_poster.py)
| Test Name | What it tests | Expected Result |
|-----------|---------------|-----------------|
| **TestBuildHeaders** | | |
| `test_headers_contain_bearer_token` | Authorization header | Header contains `Bearer <TOKEN>` |
| `test_headers_contain_accept` | Accept header | Header contains `application/vnd.github+json` |
| `test_headers_contain_api_version` | X-GitHub-Api-Version header | Header contains `2022-11-28` |
| **TestSuccessfulPost** | | |
| `test_post_returns_success` | HTTP 201 behavior | `success=True`, post called once |
| `test_comment_url_returned` | Comment URL extraction | Returned `comment_url` matches API response |
| `test_post_sends_correct_payload` | POST request payload | Request body exactly matches comment text |
| **TestDeleteExistingBotComment** | | |
| `test_deletes_previous_bot_comment` | Handling existing bot comments | DELETE API called on previous comment ID |
| `test_no_delete_when_no_bot_comment` | Handling no previous bot comments | DELETE API is not called |
| **TestFindExistingBotComment** | | |
| `test_finds_bot_comment` | Search for existing bot comment | Bot comment ID returned |
| `test_returns_none_when_no_bot_comment` | Search when no bot marker is found | `None` returned |
| `test_returns_none_on_api_error` | Search during GET API failure | `None` returned gracefully |
| **TestMissingToken** | | |
| `test_empty_token_returns_failure` | Empty token validation | `success=False`, error mentions empty/missing token |
| `test_empty_token_skips_api_calls` | Empty token API behavior | No API calls are made |
| **TestApiErrors** | | |
| `test_403_returns_failure` | HTTP 403 (insufficient permissions) | `success=False`, error includes "403" |
| `test_422_returns_failure` | HTTP 422 (validation failed) | `success=False`, error includes "422" |
| `test_network_error_returns_failure` | Network exception handling | `success=False`, error mentions network failure |
| **TestFallbackPrint** | | |
| `test_fallback_prints_comment` | Fallback on API failure | Comment body prints to stdout |
| `test_missing_token_prints_fallback` | Fallback on missing token | Comment body prints to stdout |

## Test Suite 4 — Integration Tests (test_integration.py)
| Test Name | What it tests | Expected Result |
|-----------|---------------|-----------------|
| `test_full_pipeline_clean_zone` | Pipeline execution with a clean zone | `safe_to_merge=True` and risk is LOW/CLEAN |
| `test_full_pipeline_risky_zone` | Pipeline execution with a risky zone | `safe_to_merge=False` and findings contain CRITICAL |
| `test_full_pipeline_critical_zone` | Pipeline execution with a critical zone | `valid=False` or CRITICAL finding present |
| `test_comment_formatter_clean_output` | Formatter output for clean zone | Comment contains "CLEAN" and "Safe to Merge" |
| `test_comment_formatter_critical_output`| Formatter output for critical zone | Comment contains "CRITICAL" and "❌" |
| `test_main_exits_with_code_1_on_critical`| Main script behavior on CRITICAL risk | Script terminates with SystemExit code 1 |

## How to Run Tests
```bash
pip install -r requirements.txt
python -m pytest -v
```

## Test Results Screenshot
[50 tests passing — see pytest output in CI logs]
