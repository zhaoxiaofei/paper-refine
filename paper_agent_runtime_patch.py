"""Parent-tracked F003/F024/F025 fixes for the shared agent runtime.

The shared runtime lives in the ``agent-common`` git submodule. The three
verified fixes for F003 (signature/OAuth query keys were not treated as
credentials), F024 (an ``AgentSelection`` repr that printed ``prep_json``
credentials) and F025 (an unguarded ``exc.read()`` in the shared prep proxy)
were first written as uncommitted edits inside that submodule's work tree.
Review finding R07 showed that such an edit cannot be represented in the parent
commit: ``git add`` records the submodule's old HEAD, so the parent commit would
silently omit the fixes.

R07's documented alternative is to move the changes to a parent-tracked module
and leave the submodule at its recorded gitlink commit. This module is that
parent-tracked home. Importing it installs the same behaviour on the
already-imported ``agent_common.model_runtime`` module and is idempotent.
"""
from __future__ import annotations

import contextlib
import http.client
import json
from typing import Any

from agent_common import model_runtime as rt


def _install_agent_selection_repr() -> None:
    """F024: never print a credential carried in ``prep_json``.

    ``AgentSelection.api_key`` is already ``repr=False``; ``prep_json`` is not,
    so a caller that puts a key in the request defaults leaked it through the
    auto-generated repr. The replacement mirrors the class's own repr and applies
    the shared ``redact_prep_object`` mask (the helper the fix-bugs stage used).
    """
    selection = getattr(rt, "AgentSelection", None)
    if selection is None or getattr(selection, "_paper_prep_json_repr", False):
        return

    def __repr__(self) -> str:
        model = self.model
        if self.is_endpoint and model is not None:
            try:
                model = rt.redact_endpoint_url(str(model))
            except (TypeError, ValueError):
                model = "<redacted endpoint>"
        return (
            "AgentSelection(harness=%r, model=%r, legacy=%r, model_name=%r, "
            "prep_json=%r)"
            % (self.harness, model, self.legacy, self.model_name,
               rt.redact_prep_object(self.prep_json))
        )

    selection.__repr__ = __repr__
    selection._paper_prep_json_repr = True


def _install_prep_proxy_short_read_guard() -> None:
    """F025: turn a short read of a 4xx/5xx body into a clean 502.

    ``_PrepProxyHandler._forward`` reads an HTTP error body inside its
    ``except HTTPError`` branch. An ``IncompleteRead`` raised there is not caught
    by the sibling ``except`` clauses, so it escaped ``do_POST`` and the client
    saw a closed connection. ``start_prep_proxy`` reads the module-level handler
    name at call time, so replacing it with this guarded subclass covers every
    proxy started afterwards.
    """
    base = getattr(rt, "_PrepProxyHandler", None)
    if base is None or getattr(base, "_paper_short_read_guarded", False):
        return

    class _ShortReadGuardedPrepProxyHandler(base):
        _paper_short_read_guarded = True

        def do_POST(self) -> None:
            responded = False
            original_send_response = self.send_response

            def send_response(code: int, *args: Any, **kwargs: Any) -> None:
                nonlocal responded
                responded = True
                return original_send_response(code, *args, **kwargs)

            self.send_response = send_response  # type: ignore[method-assign]
            try:
                return super().do_POST()
            except http.client.HTTPException as exc:
                if responded:
                    # Headers are already on the wire; a second response would
                    # corrupt the stream. Preserve the previous failure mode.
                    raise
                raw = json.dumps(
                    {"error": {"message": (
                        "custom endpoint proxy could not read the upstream "
                        "response body: %s" % exc)}}
                ).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                with contextlib.suppress(OSError):
                    self.wfile.write(raw)

        def do_GET(self) -> None:
            # The same forward path serves GET: an IncompleteRead in the error
            # body escaped do_POST-only guarding (F059).
            responded = False
            original_send_response = self.send_response

            def send_response(code: int, *args: Any, **kwargs: Any) -> None:
                nonlocal responded
                responded = True
                return original_send_response(code, *args, **kwargs)

            self.send_response = send_response  # type: ignore[method-assign]
            try:
                return super().do_GET()
            except http.client.HTTPException as exc:
                if responded:
                    raise
                raw = json.dumps(
                    {"error": {"message": (
                        "custom endpoint proxy could not read the upstream "
                        "response body: %s" % exc)}}
                ).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                with contextlib.suppress(OSError):
                    self.wfile.write(raw)

    rt._PrepProxyHandler = _ShortReadGuardedPrepProxyHandler


def _install_credential_key_vocabulary() -> None:
    """F003: treat signature/OAuth query-key spellings as credentials.

    ``_credential_key`` reads the module-level ``_CREDENTIAL_KEY_NAMES`` set by
    name at call time, so extending the module attribute here covers every
    caller (``endpoint_credentials``, ``split_endpoint_credentials`` and the
    probe/pair paths) without touching the submodule.
    """
    extra = frozenset({
        "sig", "signature", "xamzsignature", "xamzcredential", "xamzsecuritytoken",
        # Google Cloud Storage signed URLs carry the same three credential
        # spellings as the AWS entries above; without them a
        # `?X-Goog-Signature=` value stayed in the base URL and reached the
        # codex argv (F42).
        "xgoogsignature", "xgoogcredential", "xgoogsecuritytoken",
        "sessiontoken", "jwt", "ticket", "code", "sas", "sastoken", "idtoken",
    })
    current = getattr(rt, "_CREDENTIAL_KEY_NAMES", None)
    if not isinstance(current, frozenset) or extra <= current:
        return
    rt._CREDENTIAL_KEY_NAMES = current | extra


def install() -> None:
    """Install the parent-tracked patches; safe to call on every import."""
    _install_credential_key_vocabulary()
    _install_agent_selection_repr()
    _install_prep_proxy_short_read_guard()


install()
