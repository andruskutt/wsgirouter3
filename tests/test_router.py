"""Tests for routing functionality."""

import uuid
from typing import Optional

import pytest

from wsgirouter3 import Body, MethodNotAllowedError, NotFoundError, PathParameter, PathRouter, Query, Request


def test_str_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: str):
        pass

    r.add_route('/{req}', methods, handler)
    r.add_route('/{req}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/abc'}
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 'abc'}

    environ['PATH_INFO'] = '/def/subpath'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 'def'}

    environ['PATH_INFO'] = '/ghi'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 'ghi'}

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
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': True}

    environ['PATH_INFO'] = '/false/subpath'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': False}

    environ['PATH_INFO'] = '/on'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': True}

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
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 123}

    environ['PATH_INFO'] = '/456/subpath'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 456}

    environ['PATH_INFO'] = '/-456/subpath'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': -456}

    environ['PATH_INFO'] = '/789'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 789}

    environ['PATH_INFO'] = '/-789'
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': -789}

    environ['PATH_INFO'] = '/abc'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/def/subpath'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/jkl/mismatch'
    with pytest.raises(NotFoundError):
        r(environ)


def test_uuid_routes():
    r = PathRouter()
    methods = ('GET',)

    uid = str(uuid.uuid4())

    def handler(uid: uuid.UUID):
        pass

    r.add_route('/{uid}', methods, handler)
    r.add_route('/{uid}/subpath', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/' + uid}
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'uid': uuid.UUID(uid)}

    environ['PATH_INFO'] = '/abc-def-ghi-jkl-mno'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/abc'
    with pytest.raises(NotFoundError):
        r(environ)

    environ['PATH_INFO'] = '/def/subpath'
    with pytest.raises(NotFoundError):
        r(environ)


def test_bad_path_parameter_implementation():
    r = PathRouter()

    class BadPathParameterImplementation(PathParameter):
        # no match override
        pass

    r.parameter_types[float] = BadPathParameterImplementation

    url = '/{value}'

    @r.route(url, methods=('GET',))
    def handler(value: float):
        raise AssertionError('Cannot happen')

    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': url.format(value=3.0)}
    with pytest.raises(AttributeError):
        r(environ)


def test_optional_routes():
    r = PathRouter()
    methods = ('GET',)

    def handler(req: Optional[int]):
        pass

    r.add_route('/{req}', methods, handler)

    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': '/123'}
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'req': 123}


def test_methods_passing():
    r = PathRouter()
    methods = ('GET',)

    def handler():
        pass

    r.add_route('/tuple', methods, handler)
    r.add_route('/list', list(methods), handler)
    r.add_route('/set', set(methods), handler)
    r.add_route('/frozenset', frozenset(methods), handler)


def test_method_shortcuts():
    r = PathRouter()

    def handler():
        pass

    url = '/path'
    r.delete(url)(handler)
    r.get(url)(handler)
    r.patch(url)(handler)
    r.post(url)(handler)
    r.put(url)(handler)


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
    endpoint, path_parameters = r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url})
    assert endpoint.handler == handler
    assert path_parameters == {}

    url = '/trailing'
    r.add_route(url, methods, handler)
    endpoint, path_parameters = r({'REQUEST_METHOD': methods[0], 'PATH_INFO': url})
    assert endpoint.handler == handler
    assert path_parameters == {}

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
    endpoint, path_parameters = r(environ)
    assert endpoint.handler == handler
    assert path_parameters == {}


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

    with pytest.raises(ValueError, match='bool_param is not initialized'):
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

    def query_generic_without_t(query: Query):
        pass

    with pytest.raises(ValueError, match='parameter query is not initialized'):
        r.add_route('/', methods, query_generic_without_t)


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

    for route, url, args, _ in paths:
        environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': (url or route)}
        endpoint, path_parameters = r(environ)
        assert endpoint.handler == handler
        assert path_parameters == args


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

    with pytest.raises(ValueError, match='missing path segment'):
        router.add_subrouter('/trailing-separator/', subrouter)

    with pytest.raises(ValueError, match='duplicate subrouter'):
        router.add_subrouter(prefix1, handler)

    url = '/abc'
    environ = {'REQUEST_METHOD': methods[0], 'PATH_INFO': url}
    with pytest.raises(NotFoundError):
        router(environ)

    environ['PATH_INFO'] = prefix1 + url
    endpoint, path_parameters = router(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'value': 'abc'}

    environ['PATH_INFO'] = prefix1 + url + '/subpath'
    endpoint, path_parameters = router(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'value': 'abc'}

    environ['PATH_INFO'] = prefix2 + url
    endpoint, path_parameters = router(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'value': 'abc'}

    environ['PATH_INFO'] = prefix2 + url + '/subpath'
    endpoint, path_parameters = router(environ)
    assert endpoint.handler == handler
    assert path_parameters == {'value': 'abc'}


def test_direct_mapping():
    def handler_with_parameter(value: str):
        pass

    def handler_without_parameters():
        pass

    def handler_with_bindings(ctx: Request, args: Query[dict]):
        pass

    router = PathRouter()

    methods = ('GET',)
    router.add_route('/{value}', methods, handler_with_parameter)
    router.add_route('/{value}/subpath', methods, handler_with_parameter)

    assert len(router.direct_mapping) == 0

    router.add_route('/withdefault/subpath', methods, handler_with_parameter, {'value': 'VALUE'})

    assert len(router.direct_mapping) == 1

    router.add_route('/bindings', methods, handler_with_bindings)

    assert len(router.direct_mapping) == 2

    subrouter = PathRouter()

    subrouter.add_route('subroutes', methods, handler_without_parameters)
    subrouter.add_route('/subroutes/subpath', methods, handler_with_parameter, {'value': 'VALUE'})

    assert len(subrouter.direct_mapping) == 2

    router.add_subrouter('subroutes', subrouter)

    assert len(router.direct_mapping) == 4

    assert set(router.direct_mapping) == {
        '/withdefault/subpath', '/bindings', 'subroutes/subroutes', 'subroutes/subroutes/subpath'
    }


def test_get_routes():
    def handler(value: str):
        pass

    router = PathRouter()

    # no routes defined
    assert tuple(router.get_routes()) == ()

    methods = ('GET',)

    url = '/prefix1/{value}'
    router.add_route(url, methods, handler)

    routes = tuple(router.get_routes())
    assert len(routes) == 1
    path, method, _ = routes[0]
    assert _convert_path(path) == url
    assert method == methods[0]

    subrouter = PathRouter()
    subrouter.add_route(url, methods, handler)

    prefix = '/subrouter'
    router.add_subrouter(prefix, subrouter)

    routes = tuple(router.get_routes())
    assert len(routes) == 2
    path, method, _ = routes[1]
    assert _convert_path(path) == prefix + url
    assert method == methods[0]


def _convert_path(path):
    return '/' + '/'.join(tuple(p if isinstance(p, str) else f'{{{p.name}}}' for p in path))
