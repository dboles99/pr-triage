"""Test doubles: a fake GitHub HTTP opener. No network."""
import io
import json
import urllib.error
from email.message import Message


class _Resp(io.BytesIO):
    def __init__(self, status, headers, body):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _headers(d):
    m = Message()
    for k, v in (d or {}).items():
        m[k] = v
    return m


class FakeGitHub:
    """routes: {path_without_host: (status, headers, body_obj_or_bytes)}; unknown paths -> 404."""

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []
        self.requests = []

    def __call__(self, req, timeout=None):
        path = req.full_url.split("api.github.com/", 1)[-1]
        self.calls.append(path)
        self.requests.append({"method": req.get_method(), "path": path, "data": req.data})
        status, headers, body = self.routes.get(path, (404, {}, {"message": "Not Found"}))
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", _headers(headers), io.BytesIO(raw))
        return _Resp(status, _headers(headers), raw)
