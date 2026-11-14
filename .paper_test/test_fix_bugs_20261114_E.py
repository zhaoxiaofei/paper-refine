#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 2026-11-14 fix-bugs wave, group E.

Covers the model proxy server in paper_model_agent.py: the prep-json proxy
redirect refusal (F50), the /models probe redirect and failure reporting
(F51/F52), chunked and invalid Content-Length POST framing (F53/F54), the
endpoint parser (F60) and duplicated response headers (F61).

Hermetic: loopback servers only, no network, no real model call, tempfile-free.

Run: python3 .paper_test/test_fix_bugs_20261114_E.py
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("PAPER_WS") or HERE.parent)
FAILS = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


router = load("paper_fixbugs_E_router", WS / "paper_model_agent.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class Quiet(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""


def serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def raw(addr, payload):
    sock = socket.create_connection(addr, timeout=10)
    try:
        sock.sendall(payload)
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        sock.close()


def proxy_host_port(base):
    host, port = base.split("//", 1)[1].split("/")[0].split(":")
    return host, int(port)


def test_f50():
    print("\n== F50: the prep proxy refuses a cross-host redirect ==")
    seen = []

    class Evil(Quiet):
        def _record(self):
            seen.append(dict(self.headers))
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _record
        do_POST = _record

    evil = serve(Evil)

    class Redirect(Quiet):
        def do_POST(self):
            self.body()
            self.send_response(302)
            self.send_header("Location",
                             f"http://127.0.0.1:{evil.server_address[1]}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

    redirect = serve(Redirect)
    try:
        base, err = router.start_prep_proxy(
            f"http://127.0.0.1:{redirect.server_address[1]}/v1",
            {"temperature": 0.1})
        check("F50 the prep proxy starts", bool(base) and not err, err)
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps({"model": "m", "messages": []}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer sk-SECRET-123"}, method="POST")
        status = 0
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
        leaked = any("sk-SECRET-123" in json.dumps(h) for h in seen)
        check("F50 a 3xx is refused as 502 and never reaches the Location host",
              status == 502 and not seen and not leaked,
              f"status={status} seen={len(seen)} leaked={leaked}")
    finally:
        router.stop_prep_proxy()
        redirect.shutdown()
        evil.shutdown()


def test_f51():
    print("\n== F51: the /models probe refuses a redirect ==")
    seen = []

    class Evil(Quiet):
        def do_GET(self):
            seen.append(dict(self.headers))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = b'{"data": []}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    evil = serve(Evil)

    class Redirect(Quiet):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location",
                             f"http://127.0.0.1:{evil.server_address[1]}/models")
            self.send_header("Content-Length", "0")
            self.end_headers()

    redirect = serve(Redirect)
    try:
        cfg = {"base_url": f"http://127.0.0.1:{redirect.server_address[1]}/v1",
               "api_key": "sk-MODELS-SECRET"}
        raised = ""
        try:
            router._endpoint_catalog(cfg)
        except router.rt._EndpointProbeError as exc:
            raised = str(exc)
        leaked = any("sk-MODELS-SECRET" in json.dumps(h) for h in seen)
        check("F51 a /models redirect is a probe error, not a followed request",
              bool(raised) and not seen and not leaked,
              f"error={raised!r} seen={len(seen)}")
    finally:
        redirect.shutdown()
        evil.shutdown()


def test_f52():
    print("\n== F52: a failed /models probe is not an empty listing ==")

    class Unauthorized(Quiet):
        def do_GET(self):
            body = json.dumps({"error": {"message": "invalid key"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class NoListing(Quiet):
        def do_GET(self):
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    bad = serve(Unauthorized)
    try:
        cfg = {"base_url": f"http://127.0.0.1:{bad.server_address[1]}/v1",
               "api_key": "wrong", "model_name": "", "endpoint": "",
               "context_explicit": False}
        name, err = router.resolve_endpoint_model(cfg)
        check("F52 a 401 /models is reported, not masked as model='default'",
              name == "" and "401" in err, f"name={name!r} err={err!r}")
    finally:
        bad.shutdown()

    missing = serve(NoListing)
    try:
        cfg = {"base_url": f"http://127.0.0.1:{missing.server_address[1]}/v1",
               "api_key": "", "model_name": "", "endpoint": "",
               "context_explicit": False}
        catalog = router._endpoint_catalog(cfg)
        name, err = router.resolve_endpoint_model(cfg)
        check("F52 a 404 /models is still the documented no-listing fallback",
              catalog == [] and name == "default" and err == "",
              f"catalog={catalog} name={name!r} err={err!r}")
    finally:
        missing.shutdown()


def _framing_server(seen):
    class Up(Quiet):
        def do_POST(self):
            seen.append((self.headers.get("Transfer-Encoding"),
                         self.headers.get("Content-Length"), self.body()))
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return serve(Up)


def test_f53_f54():
    print("\n== F53/F54: unsupported request framing is rejected ==")
    for finding, headers, payload in (
        ("F53", b"Transfer-Encoding: chunked\r\n",
         b"17\r\n{\"model\":\"m\",\"messages\":[]}\r\n0\r\n\r\n"),
        ("F54", b"Content-Length: nope\r\n", b""),
    ):
        seen = []
        upstream = _framing_server(seen)
        try:
            base, err = router.start_prep_proxy(
                f"http://127.0.0.1:{upstream.server_address[1]}/v1", {})
            check(f"{finding} the prep proxy starts", bool(base) and not err, err)
            host, port = proxy_host_port(base)
            request = (b"POST /v1/chat/completions HTTP/1.1\r\n"
                       + f"Host: {host}:{port}\r\n".encode()
                       + b"Content-Type: application/json\r\n"
                       + headers
                       + b"Authorization: Bearer sk-X\r\n\r\n"
                       + payload)
            response = raw((host, port), request)
            status = response.split(b"\r\n", 1)[0]
            detail = f"status={status!r} upstream={seen!r}"
            if finding == "F53":
                check("F53 a chunked POST is rejected with 400, not forwarded empty",
                      b" 400 " in status and not seen, detail)
            else:
                check("F54 an invalid Content-Length is rejected with 400, not forwarded empty",
                      b" 400 " in status and not seen, detail)
        finally:
            router.stop_prep_proxy()
            upstream.shutdown()


def test_f60():
    print("\n== F60: the endpoint parser rejects port 0 and strips userinfo ==")
    check("F60 port 0 has no usable base URL",
          router._endpoint_base("http://example.invalid:0/v1") == "",
          repr(router._endpoint_base("http://example.invalid:0/v1")))
    check("F60 userinfo is not kept in the base URL",
          router._endpoint_base("http://user:pw@example.invalid/v1")
          == "http://example.invalid/v1",
          repr(router._endpoint_base("http://user:pw@example.invalid/v1")))
    check("F60 an out-of-range port stays rejected",
          router._endpoint_base("https://host:99999/v1") == "",
          repr(router._endpoint_base("https://host:99999/v1")))
    cfg = router.config(type("A", (), {
        "harness": "dsh", "endpoint": "http://example.invalid:0/v1",
        "api_key_env": "PAPER_AGENT_MODEL_API_KEY", "model_name": None})())
    problem = router._pair_problem(cfg)
    check("F60 --probe reports port 0 as a usage error instead of passing",
          "cannot parse endpoint URL" in problem, problem)


def test_f61():
    print("\n== F61: the proxy does not duplicate Server/Date ==")

    class Up(Quiet):
        def do_POST(self):
            body = self.body() or b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Server", "upstream-server/9")
            self.send_header("Date", "Mon, 01 Jan 2035 00:00:00 GMT")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = serve(Up)
    try:
        base, err = router.start_prep_proxy(
            f"http://127.0.0.1:{upstream.server_address[1]}/v1", {"temperature": 0.3})
        check("F61 the prep proxy starts", bool(base) and not err, err)
        host, port = proxy_host_port(base)
        request_body = json.dumps({"model": "m", "messages": []}).encode()
        payload = (b"POST /v1/chat/completions HTTP/1.0\r\n"
                   + f"Host: {host}:{port}\r\n".encode()
                   + b"Content-Type: application/json\r\n"
                   + b"Content-Length: " + str(len(request_body)).encode() + b"\r\n\r\n"
                   + request_body)
        response = raw((host, port), payload)
        head, _, body = response.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        server = [ln for ln in lines if ln.lower().startswith(b"server:")]
        date = [ln for ln in lines if ln.lower().startswith(b"date:")]
        check("F61 exactly one Server and one Date header reach the client",
              len(server) == 1 and len(date) == 1
              and b"upstream-server/9" not in head,
              f"server={server} date={date}")
        check("F61 the relayed body still carries the prep-merged request",
              b'"temperature": 0.3' in body, body[:120])
    finally:
        router.stop_prep_proxy()
        upstream.shutdown()


if __name__ == "__main__":
    test_f50()
    test_f51()
    test_f52()
    test_f53_f54()
    test_f60()
    test_f61()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        sys.exit(1)
    print("all checks passed")
