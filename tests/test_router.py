"""Tests for routing functionality."""

from typing import Optional

import pytest

from wsgirouter3 import MethodNotAllowedError, NotFoundError, PathPrefixMatchingRouter, PathRouter


def test_str_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: str):
        pass

    r.add_route('/{req}', methods, handler)
    r.add_route('/{req}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/abc'}
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 'abc'})

    environ['PATH_INFO'] = '/def/subpath'
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 'def'})

    environ['PATH_INFO'] = '/ghi'
    assert r(environ) == handler
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
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': True})

    environ['PATH_INFO'] = '/false/subpath'
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': False})

    environ['PATH_INFO'] = '/on'
    assert r(environ) == handler
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
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 123})

    environ['PATH_INFO'] = '/456/subpath'
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 456})

    environ['PATH_INFO'] = '/789'
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 789})

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
    assert r(environ) == handler
    assert environ.get(r.routing_args_key) == ((), {'req': 123})


def test_add_bad_routes():
    r = PathRouter()
    url = '/'
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

    def handler(req: str):
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

    def handler(req: str):
        pass

    r.add_route(url, methods, handler)
    assert r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url}) == handler

    url = '/trailing'
    r.add_route(url, methods, handler)
    assert r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url}) == handler

    with pytest.raises(NotFoundError, match='/trailing/'):
        r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url + '/'})

    url = '/trailing/'
    with pytest.raises(ValueError, match='missing path segment'):
        r.add_route(url, methods, handler)


def test_method_matching():
    url = '/abc'
    methods = ('GET',)

    def handler(req):
        pass

    r = PathRouter()
    r.add_route(url, methods, handler)

    environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': url}
    with pytest.raises(MethodNotAllowedError):
        r(environ)

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url}
    assert r(environ) == handler
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

    # XXX: cannot test positional-only parameter handling

    def kwhandler(**kwargs):
        pass

    with pytest.raises(ValueError, match='path parameter notdefined not defined in handler'):
        r.add_route('/{notdefined}', methods, kwhandler)

    with pytest.raises(ValueError, match='path parameter kwargs value passing by keyword not supported'):
        r.add_route('/{kwargs}', methods, kwhandler)


def test_path_parameter_typings():
    r = PathRouter()
    methods = ('GET',)

    def handler(param):
        pass

    with pytest.raises(ValueError, match='missing type annotation'):
        r.add_route('/prefix/{param}/path', methods, handler)

    def inthandler(req, int_param: int):
        pass

    # missing type in route: type is taken from signature
    r.add_route('/{int_param}/path', methods, inthandler)

    def floathandler(req, float_param: float):
        pass

    with pytest.raises(ValueError, match='unknown path parameter float_param type'):
        r.add_route('/prefix/{float_param}/path', methods, floathandler)


def test_path_parameter_defaults():
    r = PathRouter()
    methods = ('GET',)

    def handler(req, str_param: str, int_param: int, bool_param: bool, **kwargs):
        pass

    with pytest.raises(ValueError, match='cannot used as keyword arguments'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'missing': 'not there'})

    with pytest.raises(ValueError, match='cannot used as keyword arguments'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'missing': 'not there',
                                                                            'int_param': 123})

    with pytest.raises(ValueError, match='cannot used as keyword arguments'):
        r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'kwargs': 'kwargs is filtered out'})

    r.add_route('/prefix/{int_param}/path', methods, handler, defaults={'str_param': 'this is a string'})


def test_overlapping_path_segments():
    r = PathRouter()
    methods = ('GET',)

    def handler(req, variable: str):
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
        assert r(environ) == handler
        assert environ[r.routing_args_key] == ((), {**args, **(defaults or {})})


def test_prefix_matching_router():
    def handler(req: str):
        pass

    with pytest.raises(ValueError):
        PathPrefixMatchingRouter({None: handler})

    with pytest.raises(ValueError):
        PathPrefixMatchingRouter({'/': handler})

    sr = PathRouter()
    methods = ('GET',)

    sr.add_route('/{req}', methods, handler)
    sr.add_route('/{req}/subpath', methods, handler)

    prefix1 = '/subpath'
    prefix2 = '/subpath2/'
    url = '/abc'
    r = PathPrefixMatchingRouter({prefix1: sr, prefix2: sr})

    with pytest.raises(ValueError, match='Duplicate prefix'):
        r.add_route(prefix1, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': url}
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = prefix1 + url
    r(environ)

    environ['PATH_INFO'] = prefix2 + url[1:]
    r(environ)
