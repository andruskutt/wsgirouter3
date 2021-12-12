"""Tests for WSGI functionality."""

import cgi
import dataclasses
import decimal
import functools
import io
import json
import secrets
from http import HTTPStatus

import orjson

import pytest

import wsgirouter3
from wsgirouter3 import Body, HTTPError, PathRouter, Query, Request, WsgiApp, WsgiAppConfig


class JSONDecoder(json.JSONDecoder):
    def __init__(self):
        super().__init__(parse_float=decimal.Decimal)


@dataclasses.dataclass
class Sample:
    i: int
    s: str


def _http_status_response(status: HTTPStatus) -> str:
    return status.description


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


def test_request_max_request_content_length():
    conf = WsgiAppConfig()
    conf.max_request_content_length = 1
    env = {'CONTENT_LENGTH': '2'}
    r = Request(conf, env)

    with pytest.raises(HTTPError) as exc_info:
        r.body
    assert exc_info.value.args[0] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def test_request_body():
    env = {'REQUEST_METHOD': 'GET', 'CONTENT_LENGTH': '0'}
    r = Request(None, env)

    assert r.content_length == 0
    assert r.body == b''


def test_request_form_multipart_form_data():
    conf = WsgiAppConfig()
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

    r = Request(conf, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == [field_name]
    assert form_data.getfirst(field_name) == field_val


def test_request_empty_form_multipart_form_data():
    conf = WsgiAppConfig()
    boundary = secrets.token_hex(16)
    form_bytes = f'--{boundary}--\r\n'.encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': f'multipart/form-data; boundary={boundary}',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    r = Request(conf, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == []


def test_request_form_urlencoded():
    conf = WsgiAppConfig()
    field_name = 'field'
    field_val = 'FieldValue'
    form_bytes = f'{field_name}={field_val}'.encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': 'application/x-www-form-urlencoded',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    r = Request(conf, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == [field_name]
    assert form_data.getfirst(field_name) == field_val


def test_request_empty_form_urlencoded():
    conf = WsgiAppConfig()
    form_bytes = b''
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': 'application/x-www-form-urlencoded',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    r = Request(conf, env)
    assert r.content_length == len(form_bytes)
    form_data = r.form
    assert isinstance(form_data, cgi.FieldStorage)
    assert form_data.keys() == []


def test_request_bad_form():
    conf = WsgiAppConfig()
    env = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': 'application/json',
    }

    with pytest.raises(HTTPError) as exc_info:
        Request(conf, env).form
    assert exc_info.value.args[0] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    boundary = secrets.token_hex(16)
    env['CONTENT_TYPE'] = f'multipart/form-data; boundary={boundary}'
    # missing content length
    with pytest.raises(HTTPError) as exc_info:
        Request(conf, env).form
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST

    boundary = secrets.token_hex(16) + 'Ä'
    form_bytes = f'--{boundary}--\r\n'.encode()
    env['CONTENT_TYPE'] = f'multipart/form-data; boundary={boundary}'
    env['CONTENT_LENGTH'] = f'{len(form_bytes)}'
    env['wsgi.input'] = io.BytesIO(form_bytes)
    # bad boundary symbol
    with pytest.raises(HTTPError) as exc_info:
        Request(conf, env).form
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_request_json():
    env = {}
    r = Request(None, env)

    with pytest.raises(HTTPError) as exc_info:
        r.json
    assert exc_info.value.args[0] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    config = WsgiAppConfig()
    config.json_deserializer = functools.partial(json.loads, cls=JSONDecoder)
    r = Request(config, env)
    assert r.json == {'A': 1, 'B': True, 'C': None, 'D': decimal.Decimal('0.1')}


def test_request_json_orjson():
    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    config = WsgiAppConfig()
    config.json_deserializer = orjson.loads
    r = Request(config, env)
    assert r.json == {'A': 1, 'B': True, 'C': None, 'D': 0.1}


def test_request_bad_json():
    json_bytes = b'{"A": 1, "D": 0.1}'[:-2]
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    config = WsgiAppConfig()
    config.json_deserializer = functools.partial(json.loads, cls=JSONDecoder)
    r = Request(config, env)
    with pytest.raises(HTTPError) as exc_info:
        r.json
    assert exc_info.value.args[0] == HTTPStatus.BAD_REQUEST


def test_response_conversion_tuple():
    conf = WsgiAppConfig()
    env = {'REQUEST_METHOD': 'GET'}
    no_content = (HTTPStatus.NO_CONTENT, (b'',), {})

    assert conf.result_handler(env, (HTTPStatus.NO_CONTENT,)) == no_content
    assert conf.result_handler(env, (HTTPStatus.NO_CONTENT, None, ())) == no_content

    # int as status is same as HTTPStatus
    with_headers = (HTTPStatus.NO_CONTENT, (b'',), {'header': 'val'})
    assert conf.result_handler(env, (204, None, with_headers[2])) == with_headers

    with_headers = (HTTPStatus.NO_CONTENT, (b'',), {'header': 'val'})
    assert conf.result_handler(
        env,
        (HTTPStatus.NO_CONTENT, None, with_headers[2])
    ) == with_headers


def test_response_conversion_dict():
    conf = WsgiAppConfig()
    env = {'REQUEST_METHOD': 'GET'}

    json_response = (HTTPStatus.OK, (b'{"B": "blaah"}',), {'Content-Type': 'application/json', 'Content-Length': '14'})
    assert conf.result_handler(env, {'B': 'blaah'}) == json_response


def test_response_conversion_dict_orjson():
    conf = WsgiAppConfig()
    conf.json_serializer = orjson.dumps
    env = {'REQUEST_METHOD': 'GET'}

    json_response = (HTTPStatus.OK, (b'{"B":"blaah"}',), {'Content-Type': 'application/json', 'Content-Length': '13'})
    assert conf.result_handler(env, {'B': 'blaah'}) == json_response


def test_response_conversion_text():
    conf = WsgiAppConfig()
    env = {'REQUEST_METHOD': 'GET'}

    text_response = (HTTPStatus.OK, (b'blaah',), {'Content-Type': 'text/plain;charset=utf-8', 'Content-Length': '5'})
    assert conf.result_handler(env, 'blaah') == text_response


def test_response_conversion_text_custom_content_type():
    content_type = 'text/html;charset=utf-8'
    conf = WsgiAppConfig()
    conf.default_str_content_type = content_type
    env = {'REQUEST_METHOD': 'GET'}

    text_response = (HTTPStatus.OK, (b'<html></html>',), {'Content-Type': content_type, 'Content-Length': '13'})
    assert conf.result_handler(env, '<html></html>') == text_response


def test_response_conversion_binary():
    conf = WsgiAppConfig()
    env = {'REQUEST_METHOD': 'GET'}

    with_headers = (HTTPStatus.OK, b'1234', {'Content-Type': 'octet/stream'})
    assert conf.result_handler(
        env,
        with_headers
    ) == (
        with_headers[0],
        (with_headers[1],),
        {'Content-Type': 'octet/stream', 'Content-Length': '4'}
    )


def test_response_conversion_invalid():
    conf = WsgiAppConfig()
    env = {'REQUEST_METHOD': 'GET'}

    with pytest.raises(ValueError, match='Invalid result tuple'):
        conf.result_handler(env, ())

    with pytest.raises(ValueError, match='Unexpected result'):
        conf.result_handler(env, (HTTPStatus.NO_CONTENT, b'1234'))

    with pytest.raises(ValueError, match='Unexpected result'):
        conf.result_handler(env, (204, b'1234'))

    with pytest.raises(ValueError, match='Invalid type of status'):
        conf.result_handler(env, ('123 Wrong status',))

    with pytest.raises(ValueError, match='Unknown content type for binary result'):
        conf.result_handler(env, b'1234')

    with pytest.raises(ValueError, match='Unknown result'):
        conf.result_handler(env, True)


def test_dataclass_response():
    url = '/url'
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}

    response = Sample(1, 'abc')
    router = PathRouter()
    router.add_route(url, ('GET',), lambda: response)
    app = WsgiApp(router)

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
    assert WsgiAppConfig().result_handler(env, g) == (HTTPStatus.OK, g, {})

    def endpoint():
        return generator()

    router = PathRouter()
    router.add_route(url, ('GET',), endpoint)
    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert ''.join(app(env, start_response)) == '01234'


def test_custom_response():
    url = '/url'
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    result = b'12346'

    @dataclasses.dataclass
    class Custom:
        data: bytes

    router = PathRouter()

    @router.route(url, ('GET',))
    def endpoint():
        return (200, Custom(result))

    def result_converter(result: Custom, headers: dict):
        headers['Content-Length'] = str(len(result.data))
        return result.data,

    app = WsgiApp(router)
    app.config.result_converters.append((lambda result: isinstance(result, Custom), result_converter))

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == result


def test_request_content_negotiation():
    text_url = '/url/text'
    json_url = '/url/json'
    all_url = '/url/all'
    json_bytes = b'{"A": 1, "D": 0.1}'
    content = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()

    @router.route(text_url, ('GET',), consumes='text/plain')
    def text_endpoint():
        return (204,)

    @router.route(json_url, ('GET',), consumes='application/json')
    def json_endpoint():
        return (204,)

    @router.route(all_url, ('GET',), consumes=('application/json', 'text/plain'))
    def all_endpoint():
        return (204,)

    app = WsgiApp(router)
    returned_status = None

    def start_response(status, headers):
        nonlocal returned_status
        returned_status = status

    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': text_url, **content}, start_response)
    assert returned_status == '415 Unsupported Media Type'
    returned_status = None
    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': text_url, **content, 'CONTENT_TYPE': 'text/plain'}, start_response)
    assert returned_status == '204 No Content'
    returned_status = None
    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': json_url, **content}, start_response)
    assert returned_status == '204 No Content'
    returned_status = None
    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': json_url, **content, 'CONTENT_TYPE': 'text/plain'}, start_response)
    assert returned_status == '415 Unsupported Media Type'
    returned_status = None
    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': all_url, **content}, start_response)
    assert returned_status == '204 No Content'
    returned_status = None
    app({'REQUEST_METHOD': 'GET', 'PATH_INFO': all_url, **content, 'CONTENT_TYPE': 'text/plain'}, start_response)
    assert returned_status == '204 No Content'


def test_response_content_negotiation():
    url = '/url'
    router = PathRouter()

    @router.route(url, ('GET',), produces='application/json')
    def json_endpoint() -> dict:
        return {'a': 1}

    app = WsgiApp(router)
    returned_status = None

    def start_response(status, headers):
        nonlocal returned_status
        returned_status = status

    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    app({**env, 'HTTP_ACCEPT': 'text/plain'}, start_response)
    assert returned_status == '406 Not Acceptable'
    app({**env, 'HTTP_ACCEPT': 'application/json'}, start_response)
    assert returned_status == '200 OK'
    app({**env, 'HTTP_ACCEPT': '*/*'}, start_response)
    assert returned_status == '200 OK'
    app(env, start_response)
    assert returned_status == '200 OK'


def test_response_compression():
    url = '/url'
    router = PathRouter()
    strlen = 1000

    @router.route(url, ('GET',))
    def json_endpoint() -> dict:
        return {'a': 1, 'b': 'x' * strlen}

    app = WsgiApp(router)
    assert strlen >= app.config.compress_min_response_length

    headers = {}

    def start_response(status, hdrs):
        headers.update(hdrs)

    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url, 'HTTP_ACCEPT_ENCODING': 'deflate, gzip;q=1.0, *;q=0.5'}
    result = b''.join(app(env, start_response))
    assert len(result) == int(headers.get('Content-Length'))
    assert headers.get('Content-Encoding') == 'gzip'
    assert headers.get('Vary') == 'Accept-Encoding'

    headers.clear()
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url, 'HTTP_ACCEPT_ENCODING': 'deflate, gzip;q=0, *;q=0.5'}
    result = b''.join(app(env, start_response))
    assert len(result) == int(headers.get('Content-Length'))
    assert headers.get('Content-Encoding') is None
    assert headers.get('Vary') is None


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

    def endpoint():
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

    def handler():
        return {}

    def router(e):
        return handler, {}

    def start_response(status, headers):
        pass

    app = WsgiApp(router)
    app(env, start_response)

    def failingrouter(e):
        raise ValueError('Routing error')

    app = WsgiApp(failingrouter)

    def error_handler(environ, exc):
        raise exc

    app.config.error_handler = error_handler
    with pytest.raises(ValueError, match='Routing error'):
        app(env, start_response)

    url = '/url'
    r = PathRouter()

    r.add_route(url, ('GET',), lambda: {})
    app = WsgiApp(r)
    env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': url}
    assert app(env, start_response) == (_http_status_response(HTTPStatus.METHOD_NOT_ALLOWED).encode(),)

    def failinghandler():
        status = HTTPStatus.UNPROCESSABLE_ENTITY
        assert not status.description
        raise HTTPError(status)

    r = PathRouter()
    r.add_route(url, ('POST',), failinghandler)
    app = WsgiApp(r)
    assert app(env, start_response) == (_http_status_response(HTTPStatus.UNPROCESSABLE_ENTITY).encode(),)

    def handlerwithruntimeerror():
        raise ValueError('Unexpected')

    r = PathRouter()
    r.add_route(url, ('POST',), handlerwithruntimeerror)
    app = WsgiApp(r)
    assert app(env, start_response) == (_http_status_response(HTTPStatus.INTERNAL_SERVER_ERROR).encode(),)


def test_wsgi_application_head_method():
    url = '/url'
    r = PathRouter()
    r.add_route(url, ('GET',), lambda: {})
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
    r.add_route(url, ('GET', 'HEAD'), lambda: {})

    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    assert app(env, start_response) == (b'{}',)

    env = {'REQUEST_METHOD': 'HEAD', 'PATH_INFO': url}
    assert app(env, start_response) == (b'',)


def test_wsgi_application_generator_head_method():
    url = '/url'
    env = {'REQUEST_METHOD': 'HEAD', 'PATH_INFO': url}

    def endpoint():
        i = 0
        while i < 5:
            yield str(i)
            i += 1

    router = PathRouter()
    router.add_route(url, ('GET', 'HEAD'), endpoint)
    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == b''


def test_query_binding():
    url = '/url'
    env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url, 'QUERY_STRING': 'abc=def'}

    router = PathRouter()

    @router.route(url, ('GET',))
    def endpoint(query: Query[dict]) -> dict:
        return query

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == b'{"abc": "def"}'


def test_body_binding_json():
    url = '/url'
    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()

    @router.route(url, ('POST',))
    def endpoint(body: Body[dict]) -> dict:
        return body

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == json_bytes


def test_body_binding_form():
    url = '/url'
    boundary = secrets.token_hex(16)
    form_bytes = f'--{boundary}--\r\n'.encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': f'multipart/form-data; boundary={boundary}',
        'wsgi.input': io.BytesIO(form_bytes),
        'CONTENT_LENGTH': f'{len(form_bytes)}',
    }

    router = PathRouter()

    @router.route(url, ('POST',))
    def endpoint(body: Body[cgi.FieldStorage]) -> dict:
        return {key: body.getfirst(key) for key in body.keys()}

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == b'{}'


def test_body_binding_bad_datatype():
    url = '/url'
    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()

    @router.route(url, ('POST',))
    def endpoint(body: Body[list]) -> dict:
        return {'body': body}

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == _http_status_response(HTTPStatus.BAD_REQUEST).encode()


def test_body_binding_bad_content_type():
    url = '/url'
    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/octet-stream',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()

    @router.route(url, ('POST',))
    def endpoint(body: Body[dict]) -> dict:
        return body

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == _http_status_response(HTTPStatus.UNSUPPORTED_MEDIA_TYPE).encode()


def test_request_binding():
    url = '/url'
    env = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': url,
    }

    router = PathRouter()

    @router.route(url, ('GET',))
    def endpoint(request: Request) -> dict:
        return {'method': request.method}

    app = WsgiApp(router)

    def start_response(status, headers):
        pass

    assert b''.join(app(env, start_response)) == b'{"method": "GET"}'


def test_cached_property():
    calc1_called = 0

    class A:
        @wsgirouter3.cached_property
        def calc1(self):
            nonlocal calc1_called
            calc1_called += 1
            return 42

    # try to abuse descriptor protocol
    a = A.calc1
    assert isinstance(a, wsgirouter3.cached_property)

    a = A()
    for _ in range(3):
        assert a.calc1 == 42
    assert calc1_called == 1

    with pytest.raises(RuntimeError, match='Error calling __set_name__') as exc:
        class B:
            calc2 = A.calc1

    assert isinstance(exc.value.__cause__, TypeError)

    def calc():
        return 42

    p = wsgirouter3.cached_property(calc)
    with pytest.raises(TypeError, match='annot use cached_property instance without calling __set_name__'):
        p.__get__(A())


def test_http_error():
    e = HTTPError(HTTPStatus.NOT_FOUND)
    assert e.status == 404
    # result is automatically initialized
    assert e.result == _http_status_response(HTTPStatus.NOT_FOUND)
    assert e.headers is None

    e = HTTPError(HTTPStatus.NO_CONTENT)
    assert e.status == 204
    # status without result, no automatic initialization
    assert e.result is None
    assert e.headers is None
