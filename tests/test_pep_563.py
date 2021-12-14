"""Tests for postponed annotation evaluation."""

from __future__ import annotations

import io
import uuid

from wsgirouter3 import Body, PathRouter, Query, WsgiApp


def _start_response(status, headers):
    pass


def test_int_handler():
    r = PathRouter()
    url = '/url'

    @r.get(f'{url}/{{req}}')
    def handler(req: str):
        return req

    app = WsgiApp(r)

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': f'{url}/abcdef'}
    assert (b'abcdef',) == app(environ, _start_response)


def test_uuid_handler():
    r = PathRouter()
    url = '/url'

    @r.get(f'{url}/{{req}}')
    def handler(req: uuid.UUID):
        return str(req)

    app = WsgiApp(r)

    req = str(uuid.uuid4())
    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': f'{url}/{req}'}
    assert (req.encode(),) == app(environ, _start_response)


def test_body_handler():
    r = PathRouter()
    url = '/url'

    @r.post(url)
    def handler(req: Body[dict]):
        return req

    app = WsgiApp(r)

    req = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    environ = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/json',
        'CONTENT_LENGTH': len(req),
        'wsgi.input': io.BytesIO(req),
    }
    assert (req,) == app(environ, _start_response)


def test_query_handler():
    r = PathRouter()
    url = '/url'

    @r.get(url)
    def handler(req: Query[dict]):
        return req

    app = WsgiApp(r)

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url, 'QUERY_STRING': 'abc=def'}
    assert (b'{"abc": "def"}',) == app(environ, _start_response)
