"""Deployment-readiness checks for the PTAH HTTP control plane.

PTAH serves plain HTTP with the stdlib server.  This module does not create
TLS contexts or contact a network service; it only validates operator intent
before a process is started.
"""

import ipaddress

from ptah import content


def _is_loopback_binding(host):
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_deployment(host=None, token=None, tls_terminated=False,
                        require_tls=False, allow_insecure=False):
    """Return a JSON-serializable deployment readiness report.

    A non-loopback bind must have bearer authentication.  Since PTAH itself
    intentionally has no TLS implementation, non-local exposure also needs
    an explicitly declared TLS terminator unless ``allow_insecure`` is set.
    The latter is an auditable override, not a claim that PTAH provides TLS.
    """
    bind_host = str(host or content.SERVER_HOST).strip()
    local = _is_loopback_binding(bind_host)
    auth_configured = bool(str(token or "").strip())
    tls_declared = bool(tls_terminated)
    errors = []
    warnings = []

    if not local and not auth_configured:
        errors.append({
            "kind": "auth_required",
            "message": "non-loopback binding requires a bearer token",
        })
    if require_tls and not tls_declared:
        errors.append({
            "kind": "tls_required",
            "message": "TLS termination must be declared when --require-tls is set",
        })
    if not local and not tls_declared:
        item = {
            "kind": "tls_termination_required",
            "message": "PTAH serves HTTP only; declare an external TLS terminator "
                       "before exposing a non-loopback bind",
        }
        if allow_insecure:
            warnings.append(item)
        else:
            errors.append(item)
    if local and not auth_configured:
        warnings.append({
            "kind": "auth_optional_local",
            "message": "loopback binding has no bearer token",
        })
    if tls_declared:
        warnings.append({
            "kind": "tls_external",
            "message": "TLS is expected to be terminated outside PTAH",
        })
    if allow_insecure and not local:
        warnings.append({
            "kind": "insecure_override",
            "message": "non-local HTTP exposure explicitly allowed by operator",
        })

    return {
        "schema": "ptah-deployment-readiness-v1",
        "ready": not errors,
        "host": bind_host,
        "is_loopback": local,
        "auth": {
            "required": not local,
            "configured": auth_configured,
        },
        "tls": {
            "supported_by_ptah": False,
            "termination_declared": tls_declared,
            "required": bool(require_tls or not local),
        },
        "errors": errors,
        "warnings": warnings,
    }


deployment_readiness = validate_deployment
validate_deployment_readiness = validate_deployment

