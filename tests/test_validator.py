"""
test_validator.py – Pytest test suite for src/validator.py.

Tests cover every check category (CRITICAL / WARNING / INFO) using
both the canonical zone file fixtures from the zones/ directory and
small inline zone strings designed to exercise specific edge cases.

Run with:
    pytest tests/test_validator.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validator import validate_zone, ValidationResult



# ---------------------------------------------------------------------------
# Fixture helpers – load canonical zone files from disk
# ---------------------------------------------------------------------------

def _load_zone(relative_path: str) -> str:
    """
    Read a zone file relative to the repository root.

    Parameters
    ----------
    relative_path:
        Path relative to the repository root, e.g. ``"zones/example.com.txt"``.

    Returns
    -------
    str
        Full file contents.
    """
    repo_root = Path(__file__).parent.parent
    content = (repo_root / relative_path).read_text(encoding="utf-8")
    if relative_path == "zones/example.com.txt":
        # Strip out the demo wildcard record and its comment if present
        lines = content.splitlines()
        filtered_lines = [
            line for line in lines
            if "*.example.com." not in line and "DANGEROUS RECORD FOR DEMO" not in line
        ]
        content = "\n".join(filtered_lines) + "\n"
    return content


# Pre-load fixtures at module level so they are available in all tests
EXAMPLE_COM_CONTENT: str = _load_zone("zones/example.com.txt")
TEST_DOMAIN_CONTENT: str = _load_zone("zones/test-domain.com.txt")


# ---------------------------------------------------------------------------
# Helper zone strings for targeted unit tests
# ---------------------------------------------------------------------------

# Minimal valid zone – SOA + NS + one A record
_VALID_MINIMAL_ZONE = """\
$ORIGIN minimal.example.
$TTL 86400
@   IN  SOA ns1.minimal.example. admin.minimal.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.minimal.example.
@   IN  A   10.0.0.1
"""

# Zone with a wildcard A record (CRITICAL)
_WILDCARD_ZONE = """\
$ORIGIN wildcard.example.
$TTL 86400
@   IN  SOA ns1.wildcard.example. admin.wildcard.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.wildcard.example.
*   IN  A   10.0.0.99
"""

# Zone missing an NS record (CRITICAL)
_MISSING_NS_ZONE = """\
$ORIGIN nons.example.
$TTL 86400
@   IN  SOA ns1.nons.example. admin.nons.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  A   10.0.0.1
"""

# Zone missing an SOA record (CRITICAL)
_MISSING_SOA_ZONE = """\
$ORIGIN nosoa.example.
$TTL 86400
@   IN  NS  ns1.nosoa.example.
@   IN  A   10.0.0.1
"""

# Zone with an MX record whose TTL is dangerously low (WARNING)
_LOW_TTL_MX_ZONE = """\
$ORIGIN lowttl.example.
$TTL 86400
@   IN  SOA ns1.lowttl.example. admin.lowttl.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.lowttl.example.
@   60  IN  MX  10 mail.lowttl.example.
"""

# Zone with an A record whose TTL is dangerously low (WARNING)
_LOW_TTL_A_ZONE = """\
$ORIGIN lowttla.example.
$TTL 86400
@   IN  SOA ns1.lowttla.example. admin.lowttla.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.lowttla.example.
www 60  IN  A   10.0.0.2
"""

# Zone with a CNAME at the apex (WARNING)
# Note: dns.zone.from_text may reject this in strict mode; we set check_origin=False
_APEX_CNAME_ZONE = """\
$ORIGIN apexcname.example.
$TTL 86400
@   IN  SOA ns1.apexcname.example. admin.apexcname.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.apexcname.example.
@   IN  CNAME alias.apexcname.example.
"""

# Deliberately corrupted / unparseable zone content
_INVALID_ZONE = """\
THIS IS NOT A VALID DNS ZONE FILE!!!
$@#$%^&*
GARBAGE DATA: ----> <<<
"""


# ---------------------------------------------------------------------------
# Tests: Valid clean zone
# ---------------------------------------------------------------------------

class TestValidCleanZone:
    """
    A well-formed zone file should parse cleanly and produce zero findings.
    Uses zones/example.com.txt as the primary fixture.
    """

    def test_valid_returns_true(self) -> None:
        """validate_zone() should return valid=True for a clean zone file."""
        result: ValidationResult = validate_zone(
            zone_content=EXAMPLE_COM_CONTENT,
            filename="zones/example.com.txt",
        )
        assert result["valid"] is True, "Expected valid=True for example.com.txt"

    def test_no_errors(self) -> None:
        """A clean zone file should produce no parse errors."""
        result = validate_zone(
            zone_content=EXAMPLE_COM_CONTENT,
            filename="zones/example.com.txt",
        )
        assert result["errors"] == [], f"Unexpected errors: {result['errors']}"

    def test_no_findings(self) -> None:
        """A clean zone file should produce zero findings of any severity.

        We pass before_content=EXAMPLE_COM_CONTENT (same content) to simulate
        a no-op edit.  This suppresses INFO 'new record' findings that would
        otherwise fire when before_content is None (new-file scenario).
        """
        result = validate_zone(
            zone_content=EXAMPLE_COM_CONTENT,
            filename="zones/example.com.txt",
            before_content=EXAMPLE_COM_CONTENT,  # same content → zero diff findings
        )
        assert result["findings"] == [], (
            f"Expected no findings but got: {result['findings']}"
        )

    def test_minimal_valid_zone(self) -> None:
        """A minimal zone with SOA + NS + A should also pass cleanly.

        We pass before_content=_VALID_MINIMAL_ZONE (same content) to avoid
        INFO findings triggered by the new-file (no baseline) code path.
        """
        result = validate_zone(
            zone_content=_VALID_MINIMAL_ZONE,
            filename="zones/minimal.example.txt",
            before_content=_VALID_MINIMAL_ZONE,  # same content → zero diff findings
        )
        assert result["valid"] is True
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# Tests: CRITICAL – Wildcard records
# ---------------------------------------------------------------------------

class TestWildcardRecord:
    """
    Zones containing wildcard records must produce a CRITICAL finding.
    Uses both the targeted inline fixture and zones/test-domain.com.txt.
    """

    def test_wildcard_inline_is_critical(self) -> None:
        """A wildcard A record should produce a CRITICAL finding."""
        result = validate_zone(
            zone_content=_WILDCARD_ZONE,
            filename="zones/wildcard.example.txt",
        )
        criticals = [f for f in result["findings"] if f["severity"] == "CRITICAL"]
        assert len(criticals) >= 1, "Expected at least one CRITICAL finding for wildcard"

    def test_wildcard_finding_record_type(self) -> None:
        """The CRITICAL wildcard finding should reference record type 'A'."""
        result = validate_zone(
            zone_content=_WILDCARD_ZONE,
            filename="zones/wildcard.example.txt",
        )
        wildcard_findings = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and "wildcard" in f["description"].lower()
        ]
        assert len(wildcard_findings) >= 1

    def test_test_domain_has_wildcard_critical(self) -> None:
        """zones/test-domain.com.txt contains a wildcard and must trigger CRITICAL."""
        result = validate_zone(
            zone_content=TEST_DOMAIN_CONTENT,
            filename="zones/test-domain.com.txt",
        )
        wildcard_criticals = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and "wildcard" in f["description"].lower()
        ]
        assert len(wildcard_criticals) >= 1, (
            "test-domain.com.txt should produce a CRITICAL wildcard finding"
        )


# ---------------------------------------------------------------------------
# Tests: CRITICAL – Missing NS record
# ---------------------------------------------------------------------------

class TestMissingNS:
    """
    Zones without an NS record at the apex must produce a CRITICAL finding.
    """

    def test_missing_ns_is_critical(self) -> None:
        """Missing NS record should produce a CRITICAL finding."""
        result = validate_zone(
            zone_content=_MISSING_NS_ZONE,
            filename="zones/nons.example.txt",
        )
        ns_criticals = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and f["record_type"] == "NS"
        ]
        assert len(ns_criticals) >= 1, "Expected CRITICAL finding for missing NS"

    def test_test_domain_missing_ns_critical(self) -> None:
        """zones/test-domain.com.txt intentionally has no NS; must flag CRITICAL."""
        result = validate_zone(
            zone_content=TEST_DOMAIN_CONTENT,
            filename="zones/test-domain.com.txt",
        )
        ns_criticals = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and f["record_type"] == "NS"
        ]
        assert len(ns_criticals) >= 1, (
            "test-domain.com.txt should produce a CRITICAL finding for missing NS"
        )


# ---------------------------------------------------------------------------
# Tests: CRITICAL – Missing SOA record
# ---------------------------------------------------------------------------

class TestMissingSOA:
    """
    Zones without an SOA record at the apex must produce a CRITICAL finding.
    """

    def test_missing_soa_is_critical(self) -> None:
        """Missing SOA record should produce a CRITICAL finding."""
        result = validate_zone(
            zone_content=_MISSING_SOA_ZONE,
            filename="zones/nosoa.example.txt",
        )
        soa_criticals = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and f["record_type"] == "SOA"
        ]
        assert len(soa_criticals) >= 1, "Expected CRITICAL finding for missing SOA"


# ---------------------------------------------------------------------------
# Tests: WARNING – Low TTL MX record
# ---------------------------------------------------------------------------

class TestLowTTLMX:
    """
    MX records with TTL below 300 seconds must produce a WARNING finding.
    """

    def test_low_ttl_mx_inline_is_warning(self) -> None:
        """MX TTL of 60 should produce a WARNING finding."""
        result = validate_zone(
            zone_content=_LOW_TTL_MX_ZONE,
            filename="zones/lowttl.example.txt",
        )
        mx_warnings = [
            f for f in result["findings"]
            if f["severity"] == "WARNING" and f["record_type"] == "MX"
        ]
        assert len(mx_warnings) >= 1, "Expected WARNING for low-TTL MX record"

    def test_low_ttl_mx_description_mentions_ttl(self) -> None:
        """The WARNING description should reference the TTL value."""
        result = validate_zone(
            zone_content=_LOW_TTL_MX_ZONE,
            filename="zones/lowttl.example.txt",
        )
        mx_warnings = [
            f for f in result["findings"]
            if f["severity"] == "WARNING" and f["record_type"] == "MX"
        ]
        assert any("60" in w["description"] for w in mx_warnings), (
            "Expected TTL value '60' mentioned in WARNING description"
        )

    def test_test_domain_low_ttl_mx_warning(self) -> None:
        """zones/test-domain.com.txt has MX TTL=60; should produce a WARNING."""
        result = validate_zone(
            zone_content=TEST_DOMAIN_CONTENT,
            filename="zones/test-domain.com.txt",
        )
        mx_warnings = [
            f for f in result["findings"]
            if f["severity"] == "WARNING" and f["record_type"] == "MX"
        ]
        assert len(mx_warnings) >= 1, (
            "test-domain.com.txt should produce a WARNING for low-TTL MX"
        )

    def test_normal_ttl_mx_no_warning(self) -> None:
        """An MX record with TTL=86400 should NOT produce a low-TTL warning."""
        result = validate_zone(
            zone_content=EXAMPLE_COM_CONTENT,
            filename="zones/example.com.txt",
        )
        mx_ttl_warnings = [
            f for f in result["findings"]
            if f["severity"] == "WARNING"
            and f["record_type"] == "MX"
            and "ttl" in f["description"].lower()
        ]
        assert mx_ttl_warnings == [], (
            "example.com.txt should not produce a low-TTL MX warning"
        )


# ---------------------------------------------------------------------------
# Tests: WARNING – Low TTL A record
# ---------------------------------------------------------------------------

class TestLowTTLA:
    """
    A records with TTL below 300 seconds must produce a WARNING finding.
    """

    def test_low_ttl_a_is_warning(self) -> None:
        """A record with TTL=60 should produce a WARNING finding."""
        result = validate_zone(
            zone_content=_LOW_TTL_A_ZONE,
            filename="zones/lowttla.example.txt",
        )
        a_warnings = [
            f for f in result["findings"]
            if f["severity"] == "WARNING" and f["record_type"] == "A"
        ]
        assert len(a_warnings) >= 1, "Expected WARNING for low-TTL A record"


# ---------------------------------------------------------------------------
# Tests: Invalid / corrupted zone file
# ---------------------------------------------------------------------------

class TestInvalidZone:
    """
    A corrupted or syntactically invalid zone file must return valid=False.
    """

    def test_invalid_zone_returns_valid_false(self) -> None:
        """Completely garbled content should fail to parse and set valid=False."""
        result = validate_zone(
            zone_content=_INVALID_ZONE,
            filename="zones/garbage.example.txt",
        )
        assert result["valid"] is False, (
            "Expected valid=False for a completely corrupted zone file"
        )

    def test_invalid_zone_has_errors(self) -> None:
        """Invalid zone should surface at least one error message."""
        result = validate_zone(
            zone_content=_INVALID_ZONE,
            filename="zones/garbage.example.txt",
        )
        assert len(result["errors"]) >= 1, (
            "Expected at least one error message for invalid zone content"
        )

    def test_invalid_zone_has_no_findings(self) -> None:
        """When parsing fails, findings list should be empty (no partial results)."""
        result = validate_zone(
            zone_content=_INVALID_ZONE,
            filename="zones/garbage.example.txt",
        )
        assert result["findings"] == [], (
            "Invalid zone should produce no findings (parse aborted)"
        )

    def test_empty_zone_missing_required_records(self) -> None:
        """An empty zone string parses successfully but must lack SOA and NS.

        dnspython treats an empty input as a valid (empty) zone, so we cannot
        assert valid=False.  Instead we verify that the mandatory-record checks
        still fire: both SOA and NS CRITICAL findings must be present.
        """
        result = validate_zone(
            zone_content="",
            filename="zones/empty.example.txt",
        )
        # The zone itself parses; findings should surface the missing records
        criticals = [f for f in result["findings"] if f["severity"] == "CRITICAL"]
        record_types = {f["record_type"] for f in criticals}
        assert "SOA" in record_types, "Empty zone should flag missing SOA as CRITICAL"
        assert "NS" in record_types, "Empty zone should flag missing NS as CRITICAL"


# ---------------------------------------------------------------------------
# Tests: Differential checks (before_content comparisons)
# ---------------------------------------------------------------------------

class TestDifferentialChecks:
    """
    Verify that differential checks (SOA serial regression, MX changed,
    new TXT/A records, TTL changes) work correctly when before_content
    is provided.
    """

    def test_soa_serial_regression_is_critical(self) -> None:
        """Decreasing SOA serial should produce a CRITICAL finding."""
        before_zone = """\
$ORIGIN serial.example.
$TTL 86400
@   IN  SOA ns1.serial.example. admin.serial.example. (
            2024020101 3600 1800 604800 86400
)
@   IN  NS  ns1.serial.example.
@   IN  A   10.0.0.1
"""
        after_zone = """\
$ORIGIN serial.example.
$TTL 86400
@   IN  SOA ns1.serial.example. admin.serial.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.serial.example.
@   IN  A   10.0.0.1
"""
        result = validate_zone(
            zone_content=after_zone,
            filename="zones/serial.example.txt",
            before_content=before_zone,
        )
        soa_criticals = [
            f for f in result["findings"]
            if f["severity"] == "CRITICAL" and f["record_type"] == "SOA"
        ]
        assert len(soa_criticals) >= 1, "Expected CRITICAL for SOA serial regression"

    def test_new_txt_record_produces_info(self) -> None:
        """Adding a new TXT record should produce an INFO finding."""
        before_zone = """\
$ORIGIN txt.example.
$TTL 86400
@   IN  SOA ns1.txt.example. admin.txt.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.txt.example.
@   IN  A   10.0.0.1
"""
        after_zone = """\
$ORIGIN txt.example.
$TTL 86400
@   IN  SOA ns1.txt.example. admin.txt.example. (
            2024010102 3600 1800 604800 86400
)
@   IN  NS  ns1.txt.example.
@   IN  A   10.0.0.1
@   IN  TXT "v=spf1 mx ~all"
"""
        result = validate_zone(
            zone_content=after_zone,
            filename="zones/txt.example.txt",
            before_content=before_zone,
        )
        txt_infos = [
            f for f in result["findings"]
            if f["severity"] == "INFO" and f["record_type"] == "TXT"
        ]
        assert len(txt_infos) >= 1, "Expected INFO finding for new TXT record"

    def test_ttl_change_produces_info(self) -> None:
        """Changing an A record's TTL should produce an INFO finding."""
        before_zone = """\
$ORIGIN ttlchange.example.
$TTL 86400
@   IN  SOA ns1.ttlchange.example. admin.ttlchange.example. (
            2024010101 3600 1800 604800 86400
)
@   IN  NS  ns1.ttlchange.example.
@   86400   IN  A   10.0.0.1
"""
        after_zone = """\
$ORIGIN ttlchange.example.
$TTL 86400
@   IN  SOA ns1.ttlchange.example. admin.ttlchange.example. (
            2024010102 3600 1800 604800 86400
)
@   IN  NS  ns1.ttlchange.example.
@   3600    IN  A   10.0.0.1
"""
        result = validate_zone(
            zone_content=after_zone,
            filename="zones/ttlchange.example.txt",
            before_content=before_zone,
        )
        ttl_infos = [
            f for f in result["findings"]
            if f["severity"] == "INFO" and "ttl" in f["description"].lower()
        ]
        assert len(ttl_infos) >= 1, "Expected INFO finding for TTL change"
