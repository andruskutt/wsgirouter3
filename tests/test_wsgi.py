"""Tests for WSGI functionality."""

import cgi
import dataclasses
import decimal
import io
import json
import secrets
from http import HTTPStatus

import pytest

import wsgirouter3
from wsgirouter3 import HTTPError, PathRouter, Request, WsgiApp


class JSONDecoder(json.JSONDecoder):
    def __init__(self):
        super().__init__(parse_float=decimal.Decimal)


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        return json.JSONEncoder.default(self, o)


@dataclasses.dataclass
class Sample:
    i: int
    s: str


def test_request():
    env = {'REQUEST_METHOD': 'GET'}
    r = Request(None, env)

    assert r.content_type is None
    assert r.content_length == 0
    assert r.cookies is not None
    assert r.query_parameters == {}
    assert r.method == 'GET'


def test_request_bad_content_length():
    env = {'CONTENT_LENGTH': '-2'}
    r = Request(None, env)

    assert r.content_length == -2
    with pytest.raises(HTTPError) as exc_info:
        r.body
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_request_query_string():
    field_name = 'abc'
    field_value = 'def'
    env = {'REQUEST_METHOD': 'GET', 'QUERY_STRING': f'{field_name}={field_value}'}
    r = Request(None, env)
    qp = r.query_parameters
    assert qp[field_name] == field_value


def test_request_bad_query_string():
    env = {'REQUEST_METHOD': 'GET', 'QUERY_STRING': 'abc'}
    r = Request(None, env)
    with pytest.raises(HTTPError) as exc_info:
        r.query_parameters
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_request_invalid_content_length():
    env = {'CONTENT_LENGTH': 'abc'}
    r = Request(None, env)

    with pytest.raises(HTTPError) as exc_info:
        r.content_length
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_request_missing_content_length():
    env = {'REQUEST_METHOD': 'GET'}
    r = Request(None, env)

    assert r.content_length == 0
    with pytest.raises(HTTPError) as exc_info:
        r.body
    assert exc_info.value.args[0] == HTTPStatus.LENGTH_REQUIRED


def test_request_body():
    env = {'REQUEST_METHOD': 'GET', 'CONTENT_LENGTH': '0'}
    r = Request(None, env)

    assert r.content_length == 0
    assert r.body == b''


def test_request_form():
    boundary = secrets.token_hex(16)
    field_name = 'field'
    field_def = f'Content-Disposition: form-data; name="{field_name}"'
    field_val = 'FieldValue'
    form_bytes = f'--{boundary}\r\n{field_def}\r\n\r\n{field_val}\r\n'.encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': f'multipart/form-data; boundary={boundary}',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    r = Request(None, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == [field_name]


def test_request_empty_form():
    boundary = secrets.token_hex(16)
    form_bytes = f'--{boundary}--\r\n'.encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': f'multipart/form-data; boundary={boundary}',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    r = Request(None, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == []


def test_request_bad_form():
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': 'application/json',
    }

    with pytest.raises(HTTPError) as exc_info:
        Request(None, env).form
    assert exc_info.value.args[0] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    boundary = secrets.token_hex(16)
    env['CONTENT_TYPE'] = f'multipart/form-data; boundary={boundary}'
    # missing content length
    with pytest.raises(HTTPError) as exc_info:
        Request(None, env).form
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST

    boundary = secrets.token_hex(16) + 'Ä'
    form_bytes = f'--{boundary}--\r\n'.encode()
    env['CONTENT_TYPE'] = f'multipart/form-data; boundary={boundary}'
    env['CONTENT_LENGTH'] = f'{len(form_bytes)}'
    env['wsgi.input'] = io.BytesIO(form_bytes)
    # bad boundary symbol
    with pytest.raises(HTTPError) as exc_info:
        Request(None, env).form
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_request_json():
    env = {}
    r = Request(None, env)

    with pytest.raises(HTTPError) as exc_info:
        r.json
    assert exc_info.value.args[0] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    json_bytes = b'{"A": 1, "D": 0.1}'
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    app = WsgiApp(None)
    app.config.json_decoder = JSONDecoder
    r = Request(app.config, env)
    assert r.json == {'A': 1, 'D': decimal.Decimal('0.1')}


def test_request_bad_json():
    json_bytes = b'{"A": 1, "D": 0.1}'[:-2]
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    app = WsgiApp(None)
    app.config.json_decoder = JSONDecoder
    r = Request(app.config, env)
    with pytest.raises(HTTPError) as exc_info:
        r.json
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_response_conversion():
    env = {'REQUEST_METHOD': 'GET'}
    no_content = (HTTPStatus.NO_CONTENT, (b'',), {})
    assert wsgirouter3._default_result_converter(None, env, (HTTPStatus.NO_CONTENT,)) == no_content
    assert wsgirouter3._default_result_converter(None, env, (HTTPStatus.NO_CONTENT, None, ())) == no_content

    # int as status is same as HTTPStatus
    with_headers = (HTTPStatus.NO_CONTENT, (b'',), {'header': 'val'})
    assert wsgirouter3._default_result_converter(None, env, (204, None, with_headers[2])) == with_headers

    with_headers = (HTTPStatus.NO_CONTENT, (b'',), {'header': 'val'})
    assert wsgirouter3._default_result_converter(
        None,
        env,
        (HTTPStatus.NO_CONTENT, None, with_headers[2])
    ) == with_headers

    text_headers = (HTTPStatus.OK, (b'blaah',), {'Content-Type': 'text/plain', 'Content-Length': '5'})
    assert wsgirouter3._default_result_converter(None, env, 'blaah') == text_headers

    with pytest.raises(ValueError, match='Invalid result tuple'):
        wsgirouter3._default_result_converter(None, env, ())

    with pytest.raises(ValueError, match='Unexpected result'):
        wsgirouter3._default_result_converter(None, env, (HTTPStatus.NO_CONTENT, b'1234'))

    with pytest.raises(ValueError, match='Invalid type of status'):
        wsgirouter3._default_result_converter(None, env, ('123 Wrong status',))

    with pytest.raises(ValueError, match='Unknown content type for binary result'):
        wsgirouter3._default_result_converter(None, env, b'1234')

    with_headers = (HTTPStatus.OK, b'1234', {'Content-Type': 'octet/stream'})
    assert wsgirouter3._default_result_converter(
        None,
        env,
        with_headers
    ) == (
        with_headers[0],
        (with_headers[1],),
        {'Content-Type': 'octet/stream', 'Content-Length': '4'}
    )

    with pytest.raises(ValueError, match='Unknown result'):
        wsgirouter3._default_result_converter(None, env, True)


def test_dataclass_response():
    url = '/url'
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}

    response = Sample(1, 'abc')
    router = PathRouter()
    router.add_route(url, ('GET',), lambda req: response)
    app = WsgiApp(router)
    # dataclass requires support in json encoder
    app.config.json_encoder = JSONEncoder

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == b'{"i": 1, "s": "abc"}'


def test_generator_response():
    url = '/url'
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}

    def generator():
        i = 0
        while i < 5:
            yield str(i)
            i += 1

    g = generator()
    # generator is passed as is
    assert wsgirouter3._default_result_converter(None, env, g) == (HTTPStatus.OK, g, {})

    def endpoint(req):
        return generator()

    router = PathRouter()
    router.add_route(url, ('GET',), endpoint)
    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert ''.join(app(env, start_response)) == '01234'


def test_hooks():
    url = '/url'

    after_request_called = False
    before_request_called = False
    endpoint_called = False

    def after_request(status, headers, environ):
        nonlocal after_request_called
        after_request_called = True

    def before_request(request):
        nonlocal before_request_called
        before_request_called = True

    def endpoint(r):
        nonlocal endpoint_called
        endpoint_called = True
        return 200, '01234'

    router = PathRouter()
    router.add_route(url, ('GET',), endpoint)
    app = WsgiApp(router)
    app.config.after_request = after_request
    app.config.before_request = before_request

    def start_response(status, headers):
        pass

    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    assert app(env, start_response) == (b'01234',)
    assert before_request_called
    assert endpoint_called
    assert after_request_called


def test_wsgi_application():
    env = {'REQUEST_METHOD': 'GET'}

    def handler(req):
        return {}

    def router(e):
        e['wsgiorg.routing_args'] = (), {}
        return handler

    def start_response(status, headers):
        pass

    app = WsgiApp(router)
    app(env, start_response)

    def failingrouter(e):
        raise ValueError('Routing error')

    app = WsgiApp(failingrouter)

    def error_handler(app, environ, exc):
        raise exc

    app.config.error_handler = error_handler
    with pytest.raises(ValueError, match='Routing error'):
        app(env, start_response)

    url = '/url'
    r = PathRouter()

    r.add_route(url, ('GET',), lambda req: {})
    app = WsgiApp(r)
    env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': url}
    assert app(env, start_response) == (HTTPStatus.METHOD_NOT_ALLOWED.description.encode('utf-8'),)

    def failinghandler(req):
        status = HTTPStatus.UNPROCESSABLE_ENTITY
        assert not status.description
        raise HTTPError(status)

    def r(e):
        e['wsgiorg.routing_args'] = (), {}
        return failinghandler

    app = WsgiApp(r)
    assert app(env, start_response) == (HTTPStatus.UNPROCESSABLE_ENTITY.description.encode('utf-8'),)

    def handlerwithruntimeerror(req):
        raise ValueError('Unexpected')

    def r2(e):
        return handlerwithruntimeerror, {}

    app = WsgiApp(r2)
    assert app(env, start_response) == (HTTPStatus.INTERNAL_SERVER_ERROR.description.encode('utf-8'),)


def test_wsgi_application_head_method():
    url = '/url'
    r = PathRouter()
    r.add_route(url, ('GET',), lambda req: {})
    app = WsgiApp(r)

    got_headers = None

    def start_response(status, headers):
        nonlocal got_headers
        got_headers = headers

    env = {'REQUEST_METHOD': 'HEAD', 'PATH_INFO': url}
    assert app(env, start_response) == (b'',)
    assert got_headers
    assert any('Allow' == r[0] for r in got_headers)

    url = '/url/withhead'
    r.add_route(url, ('GET', 'HEAD'), lambda req: {})

    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    assert app(env, start_response) == (b'{}',)

    env = {'REQUEST_METHOD': 'HEAD', 'PATH_INFO': url}
    assert app(env, start_response) == (b'',)
