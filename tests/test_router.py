"""Tests for routing functionality."""

from typing import Optional

import pytest

from wsgirouter3 import Body, MethodNotAllowedError, NotFoundError, PathRouter, Query, Request


def test_str_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: str):
        pass

    r.add_route('/{req}', methods, handler)
    r.add_route('/{req}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/abc'}
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 'abc'})

    environ['PATH_INFO'] = '/def/subpath'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 'def'})

    environ['PATH_INFO'] = '/ghi'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 'ghi'})

    environ['PATH_INFO'] = '/jkl/mismatch'
    with pytest.raises(NotFoundError) as exc_info:
        r(environ)
    assert exc_info.value.args[0] == environ['PATH_INFO']


def test_bool_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: bool):
        pass

    r.add_route('/{req}', methods, handler)
    r.add_route('/{req}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/true'}
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': True})

    environ['PATH_INFO'] = '/false/subpath'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': False})

    environ['PATH_INFO'] = '/on'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': True})

    environ['PATH_INFO'] = '/abc'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/def/subpath'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/jkl/mismatch'
    with pytest.raises(NotFoundError):
        r(environ)


def test_int_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: int):
        pass

    r.add_route('/{req}', methods, handler)
    r.add_route('/{req}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/123'}
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 123})

    environ['PATH_INFO'] = '/456/subpath'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 456})

    environ['PATH_INFO'] = '/-456/subpath'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': -456})

    environ['PATH_INFO'] = '/789'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 789})

    environ['PATH_INFO'] = '/-789'
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': -789})

    environ['PATH_INFO'] = '/abc'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/def/subpath'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/jkl/mismatch'
    with pytest.raises(NotFoundError):
        r(environ)


def test_optional_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: Optional[int]):
        pass

    r.add_route('/{req}', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/123'}
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 123})


def test_add_bad_routes():
    r = PathRouter()
    url = '/{req}'
    methods = ('GET',)

    def handler(req: str):
        pass

    with pytest.raises(ValueError, match='no methods defined'):
        r.add_route(url, (), handler)

    with pytest.raises(ValueError, match='missing path segment'):
        r.add_route('//subpath', methods, handler)

    with pytest.raises(ValueError, match='duplicate path parameter'):
        r.add_route('/path/{req}/subpath/{req}', methods, handler)

    r.add_route(url, methods, handler)
    with pytest.raises(ValueError, match='redefinition of handler'):
        r.add_route(url, methods, handler)

    url = '/path/{req}/subpath'
    r.route(url, methods)(handler)
    with pytest.raises(ValueError, match='redefinition of handler'):
        r.route(url, methods)(handler)


@pytest.mark.parametrize('url', ('/', '/abc', '/abc/def'))
def test_match_bad_routes(url):
    r = PathRouter()
    methods = ('GET',)

    def handler():
        pass

    r.add_route(url, methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/' + url}
    with pytest.raises(NotFoundError):
        r(environ)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': url + '/'}
    with pytest.raises(NotFoundError):
        r(environ)


def test_trailing_slash():
    r = PathRouter()
    url = '/'
    methods = ('GET',)

    def handler():
        pass

    r.add_route(url, methods, handler)
    assert r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url}).__wrapped__ == handler

    url = '/trailing'
    r.add_route(url, methods, handler)
    assert r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url}).__wrapped__ == handler

    with pytest.raises(NotFoundError, match='/trailing/'):
        r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url + '/'})

    url = '/trailing/'
    with pytest.raises(ValueError, match='missing path segment'):
        r.add_route(url, methods, handler)


def test_method_matching():
    url = '/abc'
    methods = ('GET',)

    def handler():
        pass

    r = PathRouter()
    r.add_route(url, methods, handler)

    environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': url}
    with pytest.raises(MethodNotAllowedError):
        r(environ)

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    assert r(environ).__wrapped__ == handler
    assert environ.get(r.routing_args_key) == ((), {})


def test_bad_path_parameters():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: str):
        pass

    with pytest.raises(ValueError, match='invalid path parameter definition'):
        r.add_route('/{', methods, handler)

    with pytest.raises(ValueError, match='invalid path parameter definition'):
        r.add_route('/{aaa', methods, handler)

    with pytest.raises(ValueError, match='invalid path parameter definition'):
        r.add_route('/{}', methods, handler)

    with pytest.raises(ValueError, match='path parameter   not defined in handler'):
        r.add_route('/{ }', methods, handler)

    with pytest.raises(ValueError, match='path parameter 123 not defined in handler'):
        r.add_route('/{123}', methods, handler)

    with pytest.raises(ValueError, match='path parameter def not defined in handler'):
        r.add_route('/{def}', methods, handler)

    with pytest.raises(ValueError, match='path parameter abc not defined in handler'):
        r.add_route('/{abc}', methods, handler)

    with pytest.raises(ValueError, match='path parameter notdefined not defined in handler'):
        r.add_route('/{notdefined}', methods, handler)

    r.add_route('/{req}/path', methods, handler)

    def inthandler(req: int):
        pass

    with pytest.raises(ValueError, match='incompatible path parameter req'):
        r.add_route('/{req}/path', methods, inthandler)

    def argshandler(*args):
        pass

    with pytest.raises(ValueError, match='path parameter notdefined not defined in handler'):
        r.add_route('/{notdefined}', methods, argshandler)

    with pytest.raises(ValueError, match='path parameter args value passing by keyword not supported'):
        r.add_route('/{args}', methods, argshandler)

    def kwhandler(**kwargs):
        pass

    with pytest.raises(ValueError, match='path parameter notdefined not defined in handler'):
        r.add_route('/{notdefined}', methods, kwhandler)

    with pytest.raises(ValueError, match='path parameter kwargs value passing by keyword not supported'):
        r.add_route('/{kwargs}', methods, kwhandler)


def test_bad_path_parameters_internal_name():
    r = PathRouter()
    methods = ('GET',)

    # __req is internally used to pass optionally binded wsgi wrapper
    def handler_with_internal_parameter_name(__req: str):
        pass

    with pytest.raises(ValueError, match='reserved path parameter name __req'):
        r.add_route('/{__req}', methods, handler_with_internal_parameter_name)


def test_path_parameter_typings():
    r = PathRouter()
    methods = ('GET',)

    def handler(param):
        pass

    with pytest.raises(ValueError, match='missing type annotation'):
        r.add_route('/prefix/{param}/path', methods, handler)

    def inthandler(int_param: int):
        pass

    # missing type in route: type is taken from signature
    r.add_route('/{int_param}/path', methods, inthandler)

    def floathandler(float_param: float):
        pass

    with pytest.raises(ValueError, match='unknown path parameter float_param type'):
        r.add_route('/prefix/{float_param}/path', methods, floathandler)


def test_partial_path():
    url = '/extra/long'
    r = PathRouter()

    @r.route(url + '/some/suffix', ('GET',))
    def handler():
        pass

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    with pytest.raises(NotFoundError):
        r(environ)


def test_path_parameter_defaults():
    r = PathRouter()
    methods = ('GET',)

    def handler(str_param: str, int_param: int, bool_param: bool, **kwargs):
        pass

    with pytest.raises(ValueError, match='cannot used as parameters'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'missing': 'not there'})

    with pytest.raises(ValueError, match='cannot used as parameters'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'missing': 'not there',
                                                                            'int_param': 123})

    with pytest.raises(ValueError, match='cannot used as parameters'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'kwargs': 'kwargs is filtered out'})

    with pytest.raises(ValueError, match='are not initialized'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'str_param': 'this is a string'})

    r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'str_param': 'this is a string',
                                                                        'bool_param': False})


def test_bad_query_binding_parameter():
    r = PathRouter()
    methods = ('GET',)

    def too_many_queries(query1: Query[dict], query2: Query[dict]):
        pass

    with pytest.raises(ValueError, match='too many Query'):
        r.add_route('/', methods, too_many_queries)

    def only_positional_query(*query: Query[dict]):
        pass

    with pytest.raises(ValueError, match='incompatible binding parameter query'):
        r.add_route('/', methods, only_positional_query)


def test_bad_body_binding_parameter():
    r = PathRouter()
    methods = ('GET',)

    def too_many_bodies(body1: Body[dict], body2: Body[list]):
        pass

    with pytest.raises(ValueError, match='too many Body'):
        r.add_route('/', methods, too_many_bodies)

    def only_positional_body(*body: Body[dict]):
        pass

    with pytest.raises(ValueError, match='incompatible binding parameter body'):
        r.add_route('/', methods, only_positional_body)


def test_body_binding_parameter():
    r = PathRouter()
    methods = ('GET',)

    def with_body(body: Body[dict]):
        pass

    r.add_route('/', methods, with_body)


def test_request_binding_parameter():
    r = PathRouter()
    methods = ('GET',)

    def with_request(request: Request):
        pass

    r.add_route('/', methods, with_request)


def test_overlapping_path_segments():
    r = PathRouter()
    methods = ('GET',)

    def handler(variable: str):
        pass

    # route url, example request url, parameters from url, defaults
    paths = (
        ('/prefix', None, {}, {'variable': None}),
        ('/prefix/literal', None, {}, {'variable': 'something'}),
        ('/prefix/literal2', None, {}, {'variable': 'sonethingelse'}),
        ('/prefix/{variable}', '/prefix/value', {'variable': 'value'}, None),
    )
    for route, _, _, defaults in paths:
        r.add_route(route, methods, handler, defaults=defaults)

    for route, url, args, defaults in paths:
        environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': (url or route)}
        assert r(environ).__wrapped__ == handler
        assert environ[r.routing_args_key] == ((), {**args, **(defaults or {})})


def test_subrouter():
    def handler(value: str):
        pass

    router = PathRouter()
    subrouter = PathRouter()

    with pytest.raises(ValueError, match='missing path prefix for subrouter'):
        router.add_subrouter('/', subrouter)

    with pytest.raises(ValueError, match='parameters are not allowed'):
        router.add_subrouter('/{parameter}', subrouter)

    methods = ('GET',)

    subrouter.add_route('/{value}', methods, handler)
    subrouter.add_route('/{value}/subpath', methods, handler)

    prefix1 = '/subpath1'
    prefix2 = '/subpath2'

    router.add_subrouter(prefix1, subrouter)
    router.add_subrouter(prefix2, subrouter)

    with pytest.raises(ValueError, match='duplicate subrouter'):
        router.add_subrouter(prefix1, handler)

    url = '/abc'
    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': url}
    with pytest.raises(NotFoundError):
        router(environ)

    environ['PATH_INFO'] = prefix1 + url
    assert router(environ).__wrapped__ == handler
    environ['PATH_INFO'] = prefix1 + url + '/subpath'
    assert router(environ).__wrapped__ == handler

    environ['PATH_INFO'] = prefix2 + url
    assert router(environ).__wrapped__ == handler
    environ['PATH_INFO'] = prefix2 + url + '/subpath'
    assert router(environ).__wrapped__ == handler
