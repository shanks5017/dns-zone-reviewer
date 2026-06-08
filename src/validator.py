"""
validator.py – DNS zone file validator for the DNS Zone Reviewer.

Uses the dnspython library to parse RFC-1035-style zone files and
apply a suite of CRITICAL / WARNING / INFO checks.  Every check
returns a structured Finding dict so callers can filter by severity,
format output, or forward results to an AI review step.
"""

from __future__ import annotations

import sys
from typing import Literal, TypedDict

import dns.exception
import dns.name
import dns.rdataset
import dns.rdatatype
import dns.zone


# ---------------------------------------------------------------------------
# Public type contracts
# ---------------------------------------------------------------------------

Severity = Literal["CRITICAL", "WARNING", "INFO"]


class Finding(TypedDict):
    """A single validation finding attached to a zone file."""

    severity: Severity        # "CRITICAL" | "WARNING" | "INFO"
    record_type: str          # e.g. "MX", "A", "NS", "WILDCARD", "SOA"
    description: str          # Human-readable explanation
    record: str               # The actual record line that triggered this finding


class ValidationResult(TypedDict):
    """Top-level result returned by validate_zone()."""

    valid: bool               # False when the zone failed to parse at all
    errors: list[str]         # Syntax / parse error messages
    findings: list[Finding]   # Ordered list of CRITICAL → WARNING → INFO


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Minimum acceptable TTL for MX and A records.
# DNS best-practice: anything below 300 s (5 min) is considered risky because
# resolvers may not respect values lower than their own minimum TTL floor.
_MIN_SAFE_TTL: int = 300


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_finding(
    severity: Severity,
    record_type: str,
    description: str,
    record: str = "",
) -> Finding:
    """
    Construct a :class:`Finding` dict with consistent field ordering.

    Parameters
    ----------
    severity:
        One of ``"CRITICAL"``, ``"WARNING"``, or ``"INFO"``.
    record_type:
        DNS record type label, e.g. ``"MX"``, ``"A"``, ``"SOA"``.
    description:
        A human-readable sentence explaining why this finding was raised.
    record:
        The verbatim zone-file record that triggered the finding (may be
        empty when the finding is about a *missing* record).

    Returns
    -------
    Finding
        Populated TypedDict.
    """
    return Finding(
        severity=severity,
        record_type=record_type,
        description=description,
        record=record,
    )


def _record_to_str(name: dns.name.Name, rdataset: dns.rdataset.Rdataset) -> str:
    """
    Render a (name, rdataset) pair as a compact human-readable string.

    Parameters
    ----------
    name:
        The owner name of the record.
    rdataset:
        The rdataset (group of same-type records) belonging to that name.

    Returns
    -------
    str
        E.g. ``"@ 86400 IN MX 10 mail.example.com."``.
    """
    rdtype_str = dns.rdatatype.to_text(rdataset.rdtype)
    records = [f"{name} {rdataset.ttl} IN {rdtype_str} {rdata}" for rdata in rdataset]
    return "; ".join(records)


# ---------------------------------------------------------------------------
# Individual check functions – each returns a (possibly empty) list[Finding]
# ---------------------------------------------------------------------------

def _check_wildcard_records(zone: dns.zone.Zone) -> list[Finding]:
    """
    CRITICAL – Detect wildcard owner names (``*``) in the zone.

    Wildcard records match any query that is not explicitly answered by
    another record, which can silently route traffic to unexpected
    destinations.  Their presence in a PR should require explicit sign-off.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One CRITICAL finding per wildcard name detected.
    """
    findings: list[Finding] = []

    for name, node in zone.nodes.items():
        # dnspython represents the wildcard label as a single b"*" label
        if name.labels and name.labels[0] == b"*":
            for rdataset in node.rdatasets:
                findings.append(
                    _make_finding(
                        severity="CRITICAL",
                        record_type=dns.rdatatype.to_text(rdataset.rdtype),
                        description=(
                            f"Wildcard record '{name}' found. Wildcards can silently "
                            "match unintended queries and are a common source of "
                            "misconfiguration or DNS hijacking risk."
                        ),
                        record=_record_to_str(name, rdataset),
                    )
                )

    return findings


def _check_missing_ns(zone: dns.zone.Zone) -> list[Finding]:
    """
    CRITICAL – Verify that at least one NS record exists at the zone apex.

    RFC 1035 §3.3.11 requires every zone to have at least two NS records.
    A zone without any NS record is technically invalid and will fail
    delegation checks.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One CRITICAL finding when no apex NS record is found.
    """
    try:
        apex = zone.find_rdataset("@", dns.rdatatype.NS)
        if not apex:
            raise KeyError
    except (KeyError, dns.exception.DNSException):
        return [
            _make_finding(
                severity="CRITICAL",
                record_type="NS",
                description=(
                    "No NS record found at the zone apex (@). "
                    "Every valid zone MUST have at least one NS record "
                    "(RFC 1035 §3.3.11). Delegation will fail without it."
                ),
                record="",
            )
        ]
    return []


def _check_missing_soa(zone: dns.zone.Zone) -> list[Finding]:
    """
    CRITICAL – Verify that exactly one SOA record exists at the zone apex.

    The SOA record is mandatory (RFC 1035 §3.3.13).  Its absence means the
    zone is not authoritative and will be rejected by most name-server
    software.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One CRITICAL finding when no apex SOA record is found.
    """
    try:
        apex = zone.find_rdataset("@", dns.rdatatype.SOA)
        if not apex:
            raise KeyError
    except (KeyError, dns.exception.DNSException):
        return [
            _make_finding(
                severity="CRITICAL",
                record_type="SOA",
                description=(
                    "No SOA record found at the zone apex (@). "
                    "The SOA record is mandatory (RFC 1035 §3.3.13) and its "
                    "absence will cause name-server software to reject the zone."
                ),
                record="",
            )
        ]
    return []


def _check_soa_serial_regression(
    zone: dns.zone.Zone,
    before_content: str | None,
    origin: str,
) -> list[Finding]:
    """
    CRITICAL – Detect when the SOA serial number has decreased.

    DNS secondary servers use the SOA serial to decide whether to pull a new
    copy of the zone.  If the serial goes *backwards* they will never refresh,
    causing stale data to persist indefinitely on secondaries.

    Parameters
    ----------
    zone:
        The *after* (new) parsed zone.
    before_content:
        Raw text of the zone file *before* this PR.  When ``None`` or empty
        (new file) the check is skipped.
    origin:
        FQDN origin used when parsing *before_content*, e.g. ``"example.com."``.

    Returns
    -------
    list[Finding]
        One CRITICAL finding when serial regression is detected.
    """
    if not before_content:
        # New file – no baseline serial to compare against
        return []

    try:
        before_zone = dns.zone.from_text(
            before_content,
            origin=origin,
            check_origin=False,
        )
        before_soa_set = before_zone.find_rdataset("@", dns.rdatatype.SOA)
        after_soa_set = zone.find_rdataset("@", dns.rdatatype.SOA)

        before_serial: int = next(iter(before_soa_set)).serial  # type: ignore[attr-defined]
        after_serial: int = next(iter(after_soa_set)).serial    # type: ignore[attr-defined]

        if after_serial < before_serial:
            return [
                _make_finding(
                    severity="CRITICAL",
                    record_type="SOA",
                    description=(
                        f"SOA serial went backwards: {before_serial} → {after_serial}. "
                        "Secondary name servers will never pick up the updated zone "
                        "until the serial is greater than the previous value."
                    ),
                    record=f"SOA serial: {after_serial}",
                )
            ]
    except Exception as exc:  # noqa: BLE001
        # If we cannot compare, log but do not crash
        print(
            f"[validator] Could not compare SOA serials: {exc}",
            file=sys.stderr,
        )

    return []


def _check_low_ttl_mx(zone: dns.zone.Zone) -> list[Finding]:
    """
    WARNING – Flag MX records whose TTL is below the safe minimum.

    A very low TTL forces resolvers to re-query frequently, which can
    cause mail delivery failures during propagation windows and increases
    resolver load.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One WARNING per offending MX rdataset.
    """
    findings: list[Finding] = []

    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            if rdataset.rdtype == dns.rdatatype.MX and rdataset.ttl < _MIN_SAFE_TTL:
                findings.append(
                    _make_finding(
                        severity="WARNING",
                        record_type="MX",
                        description=(
                            f"MX record for '{name}' has TTL {rdataset.ttl}s, "
                            f"which is below the recommended minimum of {_MIN_SAFE_TTL}s. "
                            "Low MX TTLs can cause mail delivery failures during "
                            "DNS propagation events."
                        ),
                        record=_record_to_str(name, rdataset),
                    )
                )

    return findings


def _check_low_ttl_a(zone: dns.zone.Zone) -> list[Finding]:
    """
    WARNING – Flag A records whose TTL is below the safe minimum.

    Very short A-record TTLs increase resolver traffic and may indicate an
    unintentional change that should be reviewed before merging.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One WARNING per offending A rdataset.
    """
    findings: list[Finding] = []

    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            if rdataset.rdtype == dns.rdatatype.A and rdataset.ttl < _MIN_SAFE_TTL:
                findings.append(
                    _make_finding(
                        severity="WARNING",
                        record_type="A",
                        description=(
                            f"A record for '{name}' has TTL {rdataset.ttl}s, "
                            f"which is below the recommended minimum of {_MIN_SAFE_TTL}s. "
                            "Short TTLs increase resolver load and may expose the zone "
                            "to cache-miss amplification."
                        ),
                        record=_record_to_str(name, rdataset),
                    )
                )

    return findings


def _check_cname_at_apex(zone: dns.zone.Zone) -> list[Finding]:
    """
    WARNING – Detect a CNAME record at the zone apex (root domain).

    RFC 1034 §3.6.2 forbids CNAME records from co-existing with other record
    types.  Since the apex always has at least an SOA and NS record, a CNAME
    at ``@`` is invalid and will cause resolution failures on many resolvers.

    Parameters
    ----------
    zone:
        Parsed dnspython Zone object.

    Returns
    -------
    list[Finding]
        One WARNING finding if an apex CNAME is detected.
    """
    try:
        cname_set = zone.find_rdataset("@", dns.rdatatype.CNAME)
        if cname_set:
            return [
                _make_finding(
                    severity="WARNING",
                    record_type="CNAME",
                    description=(
                        "CNAME record at the zone apex (@) is forbidden by RFC 1034 §3.6.2. "
                        "The apex always has SOA and NS records, making a co-existing "
                        "CNAME illegal. Use an ALIAS/ANAME record or a flat A record instead."
                    ),
                    record=_record_to_str(dns.name.Name(["@"]), cname_set),
                )
            ]
    except (KeyError, dns.exception.DNSException):
        pass  # No CNAME at apex – that is fine

    return []


def _check_mx_changed(
    zone: dns.zone.Zone,
    before_content: str | None,
    origin: str,
) -> list[Finding]:
    """
    WARNING – Warn when any MX record has changed from the baseline.

    MX changes affect mail routing.  An unexpected MX modification can
    silently drop email or redirect it to an attacker-controlled host.

    Parameters
    ----------
    zone:
        The *after* (new) parsed zone.
    before_content:
        Raw zone text from before the PR.  Skipped when empty/None.
    origin:
        FQDN origin used when parsing *before_content*.

    Returns
    -------
    list[Finding]
        One WARNING per name whose MX set changed.
    """
    if not before_content:
        return []

    findings: list[Finding] = []

    try:
        before_zone = dns.zone.from_text(
            before_content,
            origin=origin,
            check_origin=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[validator] Could not parse before-zone for MX diff: {exc}", file=sys.stderr)
        return []

    # Iterate over every name in the new zone and compare MX sets.
    # We use to_digestable() (canonical wire format bytes) rather than str()
    # because str() output can vary slightly between two independently-parsed
    # zones (e.g. relative vs. absolute name forms), causing false positives.
    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            if rdataset.rdtype != dns.rdatatype.MX:
                continue

            try:
                before_mx = before_zone.find_rdataset(name, dns.rdatatype.MX)
                # Canonical wire-format bytes guarantee a stable comparison
                before_set = frozenset(r.to_digestable() for r in before_mx)
                after_set = frozenset(r.to_digestable() for r in rdataset)

                if before_set != after_set:
                    findings.append(
                        _make_finding(
                            severity="WARNING",
                            record_type="MX",
                            description=(
                                f"MX record for '{name}' has changed. "
                                "MX changes affect mail routing and should be "
                                "reviewed carefully to avoid mail loss or hijacking."
                            ),
                            record=_record_to_str(name, rdataset),
                        )
                    )
            except (KeyError, dns.exception.DNSException):
                # MX record is new (no before entry) – already covered by INFO check
                pass

    return findings


def _check_new_txt_records(
    zone: dns.zone.Zone,
    before_content: str | None,
    origin: str,
) -> list[Finding]:
    """
    INFO – Report newly added TXT records.

    New TXT records often represent SPF/DKIM/DMARC policies or ownership
    verification tokens.  They are generally benign but worth surfacing for
    awareness during review.

    Parameters
    ----------
    zone:
        The *after* (new) parsed zone.
    before_content:
        Raw zone text from before the PR.
    origin:
        FQDN origin for parsing *before_content*.

    Returns
    -------
    list[Finding]
        One INFO finding per TXT record that did not exist before.
    """
    if not before_content:
        # Brand new file – every record is "new"; report them all
        return [
            _make_finding(
                severity="INFO",
                record_type="TXT",
                description=f"New TXT record added in new zone file for '{name}'.",
                record=_record_to_str(name, rdataset),
            )
            for name, node in zone.nodes.items()
            for rdataset in node.rdatasets
            if rdataset.rdtype == dns.rdatatype.TXT
        ]

    findings: list[Finding] = []

    try:
        before_zone = dns.zone.from_text(
            before_content,
            origin=origin,
            check_origin=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[validator] Could not parse before-zone for TXT diff: {exc}", file=sys.stderr)
        return []

    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            if rdataset.rdtype != dns.rdatatype.TXT:
                continue
            try:
                before_zone.find_rdataset(name, dns.rdatatype.TXT)
                # Record existed before – not a new addition
            except (KeyError, dns.exception.DNSException):
                findings.append(
                    _make_finding(
                        severity="INFO",
                        record_type="TXT",
                        description=(
                            f"New TXT record added for '{name}'. "
                            "Verify this is intentional (SPF/DKIM/DMARC policy, "
                            "domain verification token, etc.)."
                        ),
                        record=_record_to_str(name, rdataset),
                    )
                )

    return findings


def _check_new_a_records(
    zone: dns.zone.Zone,
    before_content: str | None,
    origin: str,
) -> list[Finding]:
    """
    INFO – Report newly added A records.

    New A records indicate that a previously non-existent hostname has been
    added, which may represent new infrastructure being provisioned.

    Parameters
    ----------
    zone:
        The *after* (new) parsed zone.
    before_content:
        Raw zone text from before the PR.
    origin:
        FQDN origin for parsing *before_content*.

    Returns
    -------
    list[Finding]
        One INFO finding per A record that did not exist before.
    """
    if not before_content:
        return [
            _make_finding(
                severity="INFO",
                record_type="A",
                description=f"New A record added in new zone file for '{name}'.",
                record=_record_to_str(name, rdataset),
            )
            for name, node in zone.nodes.items()
            for rdataset in node.rdatasets
            if rdataset.rdtype == dns.rdatatype.A
        ]

    findings: list[Finding] = []

    try:
        before_zone = dns.zone.from_text(
            before_content,
            origin=origin,
            check_origin=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[validator] Could not parse before-zone for A diff: {exc}", file=sys.stderr)
        return []

    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            if rdataset.rdtype != dns.rdatatype.A:
                continue
            try:
                before_zone.find_rdataset(name, dns.rdatatype.A)
            except (KeyError, dns.exception.DNSException):
                findings.append(
                    _make_finding(
                        severity="INFO",
                        record_type="A",
                        description=(
                            f"New A record added for '{name}'. "
                            "Confirm the IP address is correct and intentional."
                        ),
                        record=_record_to_str(name, rdataset),
                    )
                )

    return findings


def _check_ttl_changes(
    zone: dns.zone.Zone,
    before_content: str | None,
    origin: str,
) -> list[Finding]:
    """
    INFO – Report any record whose TTL value changed.

    TTL changes alter cache lifetimes across the internet.  A sudden large
    increase can lock in incorrect data for hours; a dramatic decrease
    triggers excessive resolver traffic.

    Parameters
    ----------
    zone:
        The *after* (new) parsed zone.
    before_content:
        Raw zone text from before the PR.
    origin:
        FQDN origin for parsing *before_content*.

    Returns
    -------
    list[Finding]
        One INFO finding per (name, type) pair whose TTL changed.
    """
    if not before_content:
        return []

    findings: list[Finding] = []

    try:
        before_zone = dns.zone.from_text(
            before_content,
            origin=origin,
            check_origin=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[validator] Could not parse before-zone for TTL diff: {exc}", file=sys.stderr)
        return []

    for name, node in zone.nodes.items():
        for rdataset in node.rdatasets:
            rdtype_str = dns.rdatatype.to_text(rdataset.rdtype)
            try:
                before_rdataset = before_zone.find_rdataset(name, rdataset.rdtype)
                if before_rdataset.ttl != rdataset.ttl:
                    findings.append(
                        _make_finding(
                            severity="INFO",
                            record_type=rdtype_str,
                            description=(
                                f"TTL for {rdtype_str} record '{name}' changed: "
                                f"{before_rdataset.ttl}s → {rdataset.ttl}s."
                            ),
                            record=_record_to_str(name, rdataset),
                        )
                    )
            except (KeyError, dns.exception.DNSException):
                pass  # New record – covered by _check_new_* functions

    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_zone(
    zone_content: str,
    filename: str,
    before_content: str | None = None,
) -> ValidationResult:
    """
    Parse and validate a DNS zone file, returning structured findings.

    This function is the primary entry-point for the validator module.
    It runs a full suite of CRITICAL, WARNING, and INFO checks against
    the parsed zone and – when *before_content* is provided – also runs
    differential checks that compare before/after states.

    Parameters
    ----------
    zone_content:
        Full text of the zone file *after* the PR change (the new version).
    filename:
        Repository-relative path of the zone file, used to derive the
        DNS origin (e.g. ``"zones/example.com.txt"`` → ``"example.com."``).
    before_content:
        Full text of the zone file *before* the PR.  Pass ``None`` or
        ``""`` for newly created files.  Differential checks are skipped
        when this is falsy.

    Returns
    -------
    ValidationResult
        Structured dict with keys ``valid``, ``errors``, and ``findings``.
        ``valid`` is ``False`` only when the zone fails to parse entirely.

    Examples
    --------
    >>> result = validate_zone(open("zones/example.com.txt").read(), "zones/example.com.txt")
    >>> result["valid"]
    True
    >>> result["findings"]
    []
    """
    errors: list[str] = []
    findings: list[Finding] = []

    # ------------------------------------------------------------------
    # Derive the DNS origin (FQDN) from the filename.
    # Convention: zones/<domain>.txt  →  <domain>.
    # e.g. "zones/example.com.txt" → "example.com."
    # ------------------------------------------------------------------
    stem = filename.removeprefix("zones/").removesuffix(".txt")
    # Ensure origin is fully-qualified (trailing dot)
    origin: str = stem if stem.endswith(".") else f"{stem}."

    # ------------------------------------------------------------------
    # Step 1: Parse the zone file
    # ------------------------------------------------------------------
    try:
        zone = dns.zone.from_text(
            zone_content,
            origin=origin,
            check_origin=False,  # Allow zone files without an explicit $ORIGIN line
            relativize=False,    # Keep fully-qualified names for unambiguous display
        )
    except dns.exception.DNSException as exc:
        # Parsing failed – return immediately; no checks can run
        return ValidationResult(
            valid=False,
            errors=[f"Zone parse error: {exc}"],
            findings=[],
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(
            valid=False,
            errors=[f"Unexpected parse error: {exc}"],
            findings=[],
        )

    # ------------------------------------------------------------------
    # Step 2: CRITICAL checks
    # ------------------------------------------------------------------
    findings.extend(_check_wildcard_records(zone))
    findings.extend(_check_missing_ns(zone))
    findings.extend(_check_missing_soa(zone))
    findings.extend(_check_soa_serial_regression(zone, before_content, origin))

    # ------------------------------------------------------------------
    # Step 3: WARNING checks
    # ------------------------------------------------------------------
    findings.extend(_check_low_ttl_mx(zone))
    findings.extend(_check_low_ttl_a(zone))
    findings.extend(_check_cname_at_apex(zone))
    findings.extend(_check_mx_changed(zone, before_content, origin))

    # ------------------------------------------------------------------
    # Step 4: INFO checks
    # ------------------------------------------------------------------
    findings.extend(_check_new_txt_records(zone, before_content, origin))
    findings.extend(_check_new_a_records(zone, before_content, origin))
    findings.extend(_check_ttl_changes(zone, before_content, origin))

    return ValidationResult(
        valid=True,
        errors=errors,
        findings=findings,
    )
