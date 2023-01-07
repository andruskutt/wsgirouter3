"""
WSGI router.

Homepage: https://github.com/andruskutt/wsgirouter3

License: MIT
"""

import functools
import inspect
import json
import logging
import re
import sys
import zlib
from dataclasses import asdict as dataclass_asdict, dataclass, field, is_dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from types import GeneratorType
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Type, TypeVar, Union
if sys.version_info >= (3, 9):
    from collections.abc import Callable, Iterable, Mapping
    from typing import get_args, get_origin, get_type_hints, Annotated, Final
else:  # pragma: no cover
    from typing import Callable, Iterable, Mapping
    # Final is supported starting from 3.8
    from typing_extensions import get_args, get_origin, get_type_hints, Annotated, Final
from urllib.parse import parse_qsl
from uuid import UUID

__all__ = [
    'HTTPError', 'MethodNotAllowedError', 'NotFoundError',
    'PathRouter', 'PathParameter', 'RouteDefinition',
    'Request', 'WsgiApp', 'WsgiAppConfig', 'Query', 'Body', 'CacheControl',
]

_ACCEPT_ENCODING_HEADER: Final = 'Accept-Encoding'
_CONTENT_ENCODING_HEADER: Final = 'Content-Encoding'
_CONTENT_LENGTH_HEADER: Final = 'Content-Length'
_CONTENT_TYPE_HEADER: Final = 'Content-Type'
_CONTENT_TYPE_PREFIX_APPLICATION: Final = 'application/'
_CONTENT_TYPE_SUFFIX_JSON: Final = '+json'
_CONTENT_TYPE_APPLICATION_JSON: Final = _CONTENT_TYPE_PREFIX_APPLICATION + 'json'
_CONTENT_TYPE_APPLICATION_X_WWW_FORM_URLENCODED: Final = _CONTENT_TYPE_PREFIX_APPLICATION + 'x-www-form-urlencoded'
_ETAG_HEADER: Final = 'ETag'
_VARY_HEADER: Final = 'Vary'

_WEAK_VALIDATOR_PREFIX = 'W/'

_WSGI_ACCEPT_ENCODING_HEADER: Final = 'HTTP_ACCEPT_ENCODING'
_WSGI_ACCEPT_HEADER: Final = 'HTTP_ACCEPT'
_WSGI_CONTENT_LENGTH_HEADER: Final = 'CONTENT_LENGTH'
_WSGI_CONTENT_TYPE_HEADER: Final = 'CONTENT_TYPE'
_WSGI_PATH_INFO_HEADER: Final = 'PATH_INFO'
_WSGI_QUERY_STRING_HEADER: Final = 'QUERY_STRING'
_WSGI_REQUEST_METHOD_HEADER: Final = 'REQUEST_METHOD'

_NO_DATA_BODY: Final = b''
_NO_DATA_RESULT: Final = (_NO_DATA_BODY,)

_CONTENT_ENCODING_GZIP: Final = 'gzip'
_QUALITY_ZERO: Final = frozenset(('0', '0.0', '0.00', '0.000'))

_STATUSES_WITHOUT_CONTENT: Final = frozenset(
    s for s in HTTPStatus if (s >= 100 and s < 200) or s in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED)
)
_STATUS_ROW_FROM_CODE: Final = {s.value: f'{s} {s.phrase}' for s in HTTPStatus}

_PATH_SEPARATOR: Final = '/'

_SIGNATURE_CONTEXT_PARAMETER_KINDS: Final = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_SIGNATURE_ALLOWED_PARAMETER_KINDS: Final = (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)

_BOOL_TRUE_VALUES: Final = frozenset(('1', 'true', 'yes', 'on'))
_BOOL_VALUES: Final = frozenset(frozenset(('0', 'false', 'no', 'off')) | _BOOL_TRUE_VALUES)

_NONE_TYPE: Final = type(None)
F = TypeVar('F', bound=Callable[..., Any])
T = TypeVar('T')

WsgiEnviron = Dict[str, Any]
WsgiHeaders = Dict[str, str]
RouteDefinition = Tuple[Tuple[Union[str, 'PathParameter'], ...], str, Any]

_NO_POSITIONAL_ARGS: Final = ()

_logger = logging.getLogger('wsgirouter3')


class cached_property:  # noqa: N801
    """
    Cached property implementation.

    Implementation without locking, see: https://github.com/python/cpython/issues/87634
    """

    def __init__(self, func: Callable[[Any], Any]) -> None:
        self.func = func
        self.attrname: Optional[str] = None
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: Type[Any], name: str) -> None:
        if self.attrname is None:
            self.attrname = name
        elif name != self.attrname:
            raise TypeError(
                f'Cannot assign the same cached_property to two different names ({self.attrname!r} and {name!r}).'
            )

    def __get__(self, instance: Any, owner: Optional[Type[Any]] = None) -> Any:
        if instance is None:
            return self
        if self.attrname is None:
            raise TypeError('Cannot use cached_property instance without calling __set_name__ on it.')

        value = self.func(instance)
        instance.__dict__[self.attrname] = value
        return value


class HTTPError(Exception):
    def __init__(self, status: HTTPStatus, result: Any = None, headers: Optional[Dict[str, Any]] = None) -> None:
        self.status = status
        self.result = status.description if result is None and status not in _STATUSES_WITHOUT_CONTENT else result
        self.headers = headers


class NotFoundError(HTTPError):
    def __init__(self, path_info: Optional[str]) -> None:
        super().__init__(HTTPStatus.NOT_FOUND)
        self.path_info = path_info


class MethodNotAllowedError(HTTPError):
    def __init__(self, allowed: Iterable[str]) -> None:
        super().__init__(HTTPStatus.METHOD_NOT_ALLOWED, headers={'Allow': ', '.join(allowed)})
        self.allowed = frozenset(allowed)


class Request:
    def __init__(self, config: 'WsgiAppConfig', environ: WsgiEnviron) -> None:
        self.config = config
        self.environ = environ

    @cached_property
    def content_length(self) -> int:
        try:
            return int(self.environ[_WSGI_CONTENT_LENGTH_HEADER])
        except KeyError:
            return 0
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def content_type(self) -> Optional[str]:
        # rfc3875 media-type parts type / subtype are case-insensitive
        return _parse_header(self.environ.get(_WSGI_CONTENT_TYPE_HEADER))

    @property
    def content_type_application_with_json_suffix(self) -> bool:
        ct = self.content_type
        return ct and ct.startswith(_CONTENT_TYPE_PREFIX_APPLICATION) and ct.endswith(_CONTENT_TYPE_SUFFIX_JSON)

    @cached_property
    def cookies(self) -> SimpleCookie:
        return SimpleCookie(self.environ.get('HTTP_COOKIE'))

    @cached_property
    def body(self) -> bytes:
        if _WSGI_CONTENT_LENGTH_HEADER not in self.environ:
            raise HTTPError(HTTPStatus.LENGTH_REQUIRED)

        content_length = self.content_length
        if content_length < 0:
            raise HTTPError(HTTPStatus.BAD_REQUEST, 'Content-Length contains negative length')

        if content_length == 0:
            return _NO_DATA_BODY

        max_content_length = self.config.max_request_content_length
        if max_content_length is not None and max_content_length < content_length:
            raise HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

        return self.environ['wsgi.input'].read(content_length)

    @property
    def form(self) -> Dict[str, str]:
        if self.content_type != _CONTENT_TYPE_APPLICATION_X_WWW_FORM_URLENCODED:
            raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        body = self.body
        # XXX use charset from request
        return _decode_url_encoded(body.decode('utf-8'))

    @property
    def json(self) -> Any:
        if self.content_type != _CONTENT_TYPE_APPLICATION_JSON and not self.content_type_application_with_json_suffix:
            raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        try:
            return self.config.json_deserializer(self.body)
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @property
    def query_parameters(self) -> Dict[str, str]:
        qs = self.environ.get(_WSGI_QUERY_STRING_HEADER)
        return _decode_url_encoded(qs)

    @property
    def method(self) -> str:
        return self.environ[_WSGI_REQUEST_METHOD_HEADER]


@dataclass
class WsgiAppConfig:
    before_request: Optional[Callable[[Request], None]] = None
    after_request: Optional[Callable[[int, Dict[str, Any], WsgiEnviron], None]] = None
    result_converters: List[
        Tuple[Callable[[Any], bool], Callable[[Any, WsgiHeaders], Iterable[bytes]]]
    ] = field(default_factory=list)
    default_str_content_type: str = 'text/plain;charset=utf-8'
    max_request_content_length: Optional[int] = None
    compress_content_types = frozenset((_CONTENT_TYPE_APPLICATION_JSON,))
    compress_level = 2
    compress_min_response_length = 1000

    def request_factory(self, environ: WsgiEnviron) -> Request:
        return Request(self, environ)

    def result_handler(self, environ: WsgiEnviron, result: Any) -> Tuple[int, Iterable[bytes], WsgiHeaders]:
        status = HTTPStatus.OK
        headers = {}
        if isinstance(result, tuple):
            # shortcut for returning status code and optional result/headers
            tuple_length = len(result)
            if tuple_length < 1 or tuple_length > 3:
                raise ValueError(f'Invalid result tuple: {result}: supported status[, result[, headers]]')
            status = result[0]
            if not isinstance(status, int):
                raise ValueError(f'Invalid type of status: {status}')
            if tuple_length > 2 and result[2]:
                headers.update(result[2])
            result = result[1] if tuple_length > 1 else None

        if status in _STATUSES_WITHOUT_CONTENT:
            if result is not None:
                raise ValueError(f'Unexpected result for {_STATUS_ROW_FROM_CODE[status]} response')

            result = _NO_DATA_RESULT
        elif isinstance(result, dict):
            result = self.json_serializer(result)
            headers.setdefault(_CONTENT_TYPE_HEADER, _CONTENT_TYPE_APPLICATION_JSON)
            result = self.compress_result(environ, result, headers)
        elif isinstance(result, bytes):
            if _CONTENT_TYPE_HEADER not in headers:
                raise ValueError('Unknown content type for binary result')

            result = self.compress_result(environ, result, headers)
        elif isinstance(result, str):
            result = result.encode()
            headers.setdefault(_CONTENT_TYPE_HEADER, self.default_str_content_type)
            result = self.compress_result(environ, result, headers)
        elif not isinstance(result, GeneratorType):
            result = self.custom_result_handler(environ, result, headers)

        return status, result, headers

    def custom_result_handler(self, environ: WsgiEnviron, result: Any, headers: WsgiHeaders) -> Iterable[bytes]:
        for matcher, handler in self.result_converters:
            if matcher(result):
                return handler(result, headers)

        # dataclass is json if not overridden by custom converter
        if not is_dataclass(result):
            raise ValueError(f'Unknown result type: {type(result)}')

        result = self.json_serializer(result)
        headers.setdefault(_CONTENT_TYPE_HEADER, _CONTENT_TYPE_APPLICATION_JSON)
        return self.compress_result(environ, result, headers)

    def can_compress_result(self, environ: WsgiEnviron, result: bytes, headers: WsgiHeaders) -> bool:
        if self.compress_level != 0 and headers.get(_CONTENT_TYPE_HEADER) in self.compress_content_types:
            accepted_encoding = environ.get(_WSGI_ACCEPT_ENCODING_HEADER)
            if accepted_encoding is not None and _CONTENT_ENCODING_HEADER not in headers \
               and len(result) >= self.compress_min_response_length:
                for ae in accepted_encoding.split(','):
                    if _parse_header_with_quality(ae.lstrip()) == _CONTENT_ENCODING_GZIP:
                        return True
        return False

    def compress_result(self, environ: WsgiEnviron, result: bytes, headers: WsgiHeaders) -> Iterable[bytes]:
        if self.can_compress_result(environ, result, headers):
            co = zlib.compressobj(level=self.compress_level, wbits=16 + zlib.MAX_WBITS)
            result = co.compress(result)
            result_tail = co.flush()

            headers[_CONTENT_ENCODING_HEADER] = _CONTENT_ENCODING_GZIP
            vary = headers.get(_VARY_HEADER)
            headers[_VARY_HEADER] = _ACCEPT_ENCODING_HEADER if vary is None else f'{vary},{_ACCEPT_ENCODING_HEADER}'

            etag = headers.get(_ETAG_HEADER)
            if etag and etag[0] == '"':
                # https://datatracker.ietf.org/doc/html/rfc9110#section-8.8.3
                headers[_ETAG_HEADER] = _WEAK_VALIDATOR_PREFIX + etag

            tail_length = len(result_tail)
            if tail_length > 0:
                headers[_CONTENT_LENGTH_HEADER] = str(len(result) + tail_length)
                return (result, result_tail)

        headers[_CONTENT_LENGTH_HEADER] = str(len(result))
        return (result,)

    def error_handler(self, environ: WsgiEnviron, exc: Exception) -> Any:
        if not isinstance(exc, HTTPError):
            _logger.exception('Unhandled exception', exc_info=exc)

            exc = HTTPError(HTTPStatus.INTERNAL_SERVER_ERROR)

        return exc.status, exc.result, exc.headers

    def json_deserializer(self, obj: bytes) -> Any:
        return json.loads(obj)

    def json_serializer(self, obj: Any) -> bytes:
        if not isinstance(obj, dict) and is_dataclass(obj):
            obj = dataclass_asdict(obj)

        # always utf-8: https://tools.ietf.org/html/rfc8259#section-8.1
        return json.dumps(obj).encode()

    def binder(self, data: Any, result_type: Type[T]) -> T:
        if not isinstance(data, result_type):
            raise HTTPError(HTTPStatus.BAD_REQUEST)

        return data


class WsgiApp:
    # environ keys for routing data
    route_options_key: str = 'route.options'
    routing_args_key: str = 'wsgiorg.routing_args'

    def __init__(self, router: 'PathRouter', config: Optional[WsgiAppConfig] = None) -> None:
        self.router = router
        self.config = config or WsgiAppConfig()

    def __call__(self, environ: WsgiEnviron, start_response: Callable[[str, List[tuple]], Any]) -> Iterable[bytes]:
        cache_control = None

        try:
            endpoint, path_parameters = self.router(environ)
            environ[self.route_options_key] = endpoint.options
            cache_control = endpoint.cache_control

            request = self.config.request_factory(environ)
            before_request = self.config.before_request
            if before_request is not None:
                before_request(request)

            kwargs = self.bind_parameters(endpoint, path_parameters, request)
            environ[self.routing_args_key] = (_NO_POSITIONAL_ARGS, kwargs)

            result = endpoint.handler(**kwargs)
        except Exception as exc:  # noqa: B902
            result = self.config.error_handler(environ, exc)

        # XXX error handling for result conversion and after request hook
        status, result, response_headers = self.config.result_handler(environ, result)

        if cache_control is not None:
            cache_control.apply(status, response_headers, environ)

        after_request = self.config.after_request
        if after_request is not None:
            after_request(status, response_headers, environ)

        if environ[_WSGI_REQUEST_METHOD_HEADER] == 'HEAD':
            # XXX close possible file-like object in result
            result_close = getattr(result, 'close', None)
            if result_close is not None:
                result_close()
            result = _NO_DATA_RESULT

        start_response(_STATUS_ROW_FROM_CODE[status], [*response_headers.items()])
        return result

    def bind_parameters(self, endpoint: 'Endpoint', path_parameters: Dict[str, Any], req: Request) -> Dict[str, Any]:
        kwargs = path_parameters if endpoint.defaults is None else {**endpoint.defaults, **path_parameters}
        query_binding = endpoint.query_binding
        if query_binding is not None:
            data = req.query_parameters
            kwargs[query_binding[0]] = self.config.binder(data, query_binding[1])

        body_binding = endpoint.body_binding
        if body_binding is not None:
            if req.content_type == _CONTENT_TYPE_APPLICATION_JSON:
                data = req.json
            else:
                data = req.form

            kwargs[body_binding[0]] = self.config.binder(data, body_binding[1])

        request_binding = endpoint.request_binding
        if request_binding is not None:
            kwargs[request_binding[0]] = req

        return kwargs


class CacheControl:
    __slots__ = ('cache_control_header',)

    no_store: 'CacheControl'

    def __init__(self, cache_control_header: str) -> None:
        self.cache_control_header = cache_control_header

    def apply(self, status: int, response_headers: WsgiHeaders, environ: WsgiEnviron) -> None:
        if 200 <= status < 400:
            response_headers['Cache-Control'] = self.cache_control_header

    @staticmethod
    def of(max_age: int, *, immutable: bool = True, private: bool = True, public: bool = False) -> 'CacheControl':
        if max_age < 0:
            raise ValueError(f'Invalid max_age={max_age}')

        parameters = [f'max-age={int(max_age)}']
        if immutable:
            parameters.append('immutable')
        if private:
            parameters.append('private')
        if public:
            parameters.append('public')
        return CacheControl(', '.join(parameters))


CacheControl.no_store = CacheControl('no-store')


class Endpoint:
    __slots__ = (
        'handler', 'defaults', 'options', 'consumes', 'produces',
        'query_binding', 'body_binding', 'request_binding', 'cache_control'
    )

    def __init__(self, handler: Callable[..., Any],
                 defaults: Optional[Mapping[str, Any]], options: Any,
                 consumes: Union[str, Iterable[str], None], produces: Optional[str],
                 query_binding: Optional[Tuple[str, Any]],
                 body_binding: Optional[Tuple[str, Any]],
                 request_binding: Optional[Tuple[str, Any]],
                 cache_control: Optional[CacheControl]) -> None:
        self.handler = handler
        self.defaults = dict(defaults) if defaults else None
        self.options = options
        if consumes:
            self.consumes: Optional[FrozenSet[str]] = frozenset((consumes,) if isinstance(consumes, str) else consumes)
        else:
            self.consumes = None
        self.produces = produces
        self.query_binding = query_binding
        self.body_binding = body_binding
        self.request_binding = request_binding
        self.cache_control = cache_control


class PathEntry:
    __slots__ = ('mapping', 'parameter', 'methodmap', 'subrouter')

    def __init__(self) -> None:
        self.mapping: Dict[str, 'PathEntry'] = {}
        self.parameter: Optional['PathParameter'] = None
        self.methodmap: Dict[str, Endpoint] = {}
        self.subrouter: Optional['PathRouter'] = None

    def __getitem__(self, path_segment: str) -> 'PathEntry':
        handler = self.mapping.get(path_segment)
        if handler is not None:
            return handler

        if self.parameter is not None and self.parameter.match(path_segment):
            return self.parameter

        if self.subrouter is not None:
            # continue using subrouter routing tree
            # adjusting of SCRIPT_NAME and PATH_INFO is not required
            return self.subrouter.root[path_segment]

        # no match
        raise KeyError

    def add_endpoint(self, methods: Iterable[str], endpoint: Endpoint) -> None:
        self.methodmap.update(dict.fromkeys(methods, endpoint))


class QueryBinding:
    """Marker for query string binding."""


class BodyBinding:
    """Marker for body binding."""


Query = Annotated[T, QueryBinding]
Body = Annotated[T, BodyBinding]


class PathParameter(PathEntry):
    __slots__ = ('name',)

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def match(self, path_segment: str) -> bool:
        """Return True if path segment matches parameter definition."""
        return False

    def accept(self, kwargs: Dict[str, Any], path_segment: str) -> None:
        """Update kwargs with parameter parsing result."""


class BoolPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        return path_segment in _BOOL_VALUES

    def accept(self, kwargs: Dict[str, Any], path_segment: str) -> None:
        kwargs[self.name] = path_segment in _BOOL_TRUE_VALUES


class IntPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        return bool(path_segment and (path_segment[1:] if path_segment[0] == '-' else path_segment).isdecimal())

    def accept(self, kwargs: Dict[str, Any], path_segment: str) -> None:
        kwargs[self.name] = int(path_segment)


class StringPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        # do not allow zero-length strings
        return bool(path_segment)

    def accept(self, kwargs: Dict[str, Any], path_segment: str) -> None:
        # XXX should decode path segment?
        kwargs[self.name] = path_segment


class UUIDPathParameter(PathParameter):

    matcher = re.compile(r'^[\dA-Fa-f]{8}-[\dA-Fa-f]{4}-[\dA-Fa-f]{4}-[\dA-Fa-f]{4}-[\dA-Fa-f]{12}$').match

    def match(self, path_segment: str) -> bool:
        return UUIDPathParameter.matcher(path_segment) is not None

    def accept(self, kwargs: Dict[str, Any], path_segment: str) -> None:
        kwargs[self.name] = UUID(path_segment)


_DEFAULT_PARAMETER_TYPE_MAP: Final = {
    bool: BoolPathParameter,
    int: IntPathParameter,
    str: StringPathParameter,
    UUID: UUIDPathParameter,
}


class PathRouter:
    # path parameter markers, by default RFC 6570 level 1
    path_parameter_start: str = '{'
    path_parameter_end: Optional[str] = '}'
    # handler parameter types to be injected with request wrapper created by config.request_factory
    supported_request_types: Set[Type[Request]] = {Request}

    def __init__(self) -> None:
        self.root = PathEntry()
        self.parameter_types = _DEFAULT_PARAMETER_TYPE_MAP.copy()
        self.default_options = None
        self.direct_mapping: Dict[str, PathEntry] = {}

    def __call__(self, environ: WsgiEnviron) -> Tuple[Endpoint, Dict[str, Any]]:
        """Route resolver."""
        path_parameters: Dict[str, Any] = {}
        route_path = environ[_WSGI_PATH_INFO_HEADER]
        entry = self.direct_mapping.get(route_path)
        if entry is None:
            entry = self.root
            if route_path and route_path != _PATH_SEPARATOR:
                try:
                    for path_segment in _split_route_path(route_path):
                        entry = entry[path_segment]
                        if isinstance(entry, PathParameter):
                            entry.accept(path_parameters, path_segment)
                except KeyError:
                    raise NotFoundError(route_path) from None

            if not entry.methodmap:
                # intermediate path segment, no endpoints defined
                raise NotFoundError(route_path)

        endpoint = self.negotiate_endpoint(environ, entry)
        return endpoint, path_parameters

    def negotiate_endpoint(self, environ: WsgiEnviron, entry: PathEntry) -> Endpoint:
        method = environ[_WSGI_REQUEST_METHOD_HEADER]
        try:
            endpoint = entry.methodmap[method]
        except KeyError:
            raise MethodNotAllowedError(tuple(entry.methodmap.keys())) from None

        required_content_type = endpoint.consumes
        if required_content_type:
            actual_content_type = _parse_header(environ.get(_WSGI_CONTENT_TYPE_HEADER))
            if actual_content_type not in required_content_type:
                raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        response_content_type = endpoint.produces
        if response_content_type:
            accepted_media_ranges = environ.get(_WSGI_ACCEPT_HEADER)
            if accepted_media_ranges:
                for ct in accepted_media_ranges.split(','):
                    media_range = _parse_header_with_quality(ct.lstrip())
                    # XXX partial media range support: type/*
                    if response_content_type == media_range or media_range == '*/*':
                        break
                else:
                    raise HTTPError(HTTPStatus.NOT_ACCEPTABLE)

        return endpoint

    def route(self,
              route_path: str,
              methods: Iterable[str],
              defaults: Optional[Mapping[str, Any]] = None,
              options: Any = None,
              consumes: Union[str, Iterable[str], None] = None,
              produces: Optional[str] = None,
              cache_control: Optional[CacheControl] = None) -> Callable[[F], F]:
        def wrapper(handler: F) -> F:
            self.add_route(route_path, methods, handler, defaults, options, consumes, produces, cache_control)
            return handler

        return wrapper

    delete = functools.partialmethod(route, methods=('DELETE',))
    get = functools.partialmethod(route, methods=('GET',))
    patch = functools.partialmethod(route, methods=('PATCH',))
    post = functools.partialmethod(route, methods=('POST',))
    put = functools.partialmethod(route, methods=('PUT',))

    def add_route(self,
                  route_path: str,
                  methods: Iterable[str],
                  handler: Callable[..., Any],
                  defaults: Optional[Mapping[str, Any]] = None,
                  options: Any = None,
                  consumes: Union[str, Iterable[str], None] = None,
                  produces: Optional[str] = None,
                  cache_control: Optional[CacheControl] = None) -> None:
        if not (route_path and route_path.startswith(_PATH_SEPARATOR)):
            raise ValueError(f'Route path must start with {_PATH_SEPARATOR}')
        if not methods:
            raise ValueError(f'{route_path}: no methods defined')

        type_hints = get_type_hints(handler, include_extras=True)
        signature = inspect.signature(handler)
        entry, parameter_names = self.parse_route_path(route_path, signature, type_hints)
        contains_path_parameters = bool(parameter_names)

        parameters = list(signature.parameters.values())

        query_binding = self.get_binding_parameter(route_path, parameter_names, parameters, type_hints, QueryBinding)
        body_binding = self.get_binding_parameter(route_path, parameter_names, parameters, type_hints, BodyBinding)
        request_binding = self.get_binding_parameter(route_path, parameter_names, parameters, type_hints, Request)

        if defaults is not None:
            self.verify_defaults(route_path, parameter_names, defaults, parameters, type_hints)

        # check that all handler parameters are set or have default values
        required_parameters = {p.name for p in parameters
                               if p.kind in _SIGNATURE_ALLOWED_PARAMETER_KINDS and p.default is inspect.Parameter.empty}

        missing_parameters = required_parameters - parameter_names
        if defaults is not None:
            missing_parameters = missing_parameters - defaults.keys()
        if missing_parameters:
            missing = ', '.join(missing_parameters)
            plural = len(missing_parameters) > 1
            raise ValueError(
                f'{route_path}: parameter{"s" if plural else ""} {missing} {"are" if plural else "is"} not initialized'
            )

        existing = set(methods) & entry.methodmap.keys()
        if existing:
            plural = len(existing) > 1
            raise ValueError(
                f'{route_path}: redefinition of handler for method{"s" if plural else ""} {", ".join(existing)}'
            )

        endpoint = Endpoint(
            handler,
            defaults,
            self.default_options if options is None else options,
            consumes,
            produces,
            query_binding,
            body_binding,
            request_binding,
            cache_control
        )
        entry.add_endpoint(methods, endpoint)
        if not contains_path_parameters:
            self.direct_mapping[route_path] = entry

    def add_subrouter(self, route_path: str, router: 'PathRouter') -> None:
        if not (route_path and route_path.startswith(_PATH_SEPARATOR)):
            raise ValueError(f'Route path must start with {_PATH_SEPARATOR}')

        entry, _ = self.parse_route_path(route_path, None, None)
        if entry is self.root:
            raise ValueError(f'{route_path}: missing path prefix for subrouter')

        if entry.subrouter is not None:
            raise ValueError(f'{route_path}: duplicate subrouter')

        entry.subrouter = router

        def sub_path(prefix: str, path: str) -> str:
            if path == _PATH_SEPARATOR:
                return prefix
            return prefix + (path if path.startswith(_PATH_SEPARATOR) else _PATH_SEPARATOR + path)

        self.direct_mapping.update((sub_path(route_path, p), e) for p, e in router.direct_mapping.items())

    def parse_route_path(self,
                         route_path: str,
                         signature: Optional[inspect.Signature],
                         type_hints: Optional[Mapping[str, Any]]) -> Tuple[PathEntry, Set[str]]:
        entry = self.root
        parameter_names: Set[str] = set()

        if route_path == _PATH_SEPARATOR:
            return entry, parameter_names

        for path_segment in _split_route_path(route_path):
            if not path_segment:
                raise ValueError(f'{route_path}: missing path segment')

            if path_segment.startswith(self.path_parameter_start):
                # path parameter definition
                if signature is None or type_hints is None:
                    raise ValueError(f'{route_path}: parameters are not allowed')

                factory, parameter_name = self.parse_parameter(path_segment, route_path, signature, type_hints)
                if entry.parameter:
                    if not (isinstance(entry.parameter, factory) and entry.parameter.name == parameter_name):
                        raise ValueError(f'{route_path}: incompatible path parameter {parameter_name}')
                else:
                    if parameter_name in parameter_names:
                        raise ValueError(f'{route_path}: duplicate path parameter {parameter_name}')

                    entry.parameter = factory(parameter_name)

                parameter_names.add(parameter_name)
                entry = entry.parameter
            else:
                mappingentry = entry.mapping.get(path_segment)
                if mappingentry is None:
                    entry.mapping[path_segment] = mappingentry = PathEntry()

                entry = mappingentry

        return entry, parameter_names

    def parse_parameter(self,
                        parameter: str,
                        route_path: str,
                        signature: inspect.Signature,
                        type_hints: Mapping[str, Any]) -> Tuple[Type[PathParameter], str]:
        suffix_length = -len(self.path_parameter_end) if self.path_parameter_end else None
        parameter_name = parameter[len(self.path_parameter_start):suffix_length]
        if not parameter_name or (self.path_parameter_end and not parameter.endswith(self.path_parameter_end)):
            raise ValueError(f'{route_path}: invalid path parameter definition {parameter}')

        try:
            parameter_signature = signature.parameters[parameter_name]
        except KeyError:
            raise ValueError(f'{route_path}: path parameter {parameter_name} not defined in handler') from None

        if parameter_signature.kind not in _SIGNATURE_ALLOWED_PARAMETER_KINDS:
            raise ValueError(f'{route_path}: path parameter {parameter_name} value passing by keyword not supported')

        annotation = type_hints.get(parameter_name)
        if annotation is None:
            raise ValueError(f'{route_path}: path parameter {parameter_name} missing type annotation')

        annotation = _unwrap_type_annotation(annotation)

        try:
            factory = self.parameter_types[annotation]
        except KeyError:
            raise ValueError(f'{route_path}: unknown path parameter {parameter_name} type {annotation}') from None

        return factory, parameter_name

    def get_binding_parameter(self,
                              route_path: str,
                              parameter_names: Set[str],
                              parameters: List[inspect.Parameter],
                              type_hints: Mapping[str, Any],
                              binding_type: Any) -> Optional[Tuple[str, Any]]:
        is_request_binding = binding_type is Request
        if is_request_binding:
            bindings = [p for p in parameters if type_hints.get(p.name) in self.supported_request_types]
        else:
            bindings = [p for p in parameters if _is_annotated_with(type_hints.get(p.name), binding_type)]

        if len(bindings) > 1:
            raise ValueError(f'{route_path}: too many {binding_type.__name__}[] annotated parameters')

        if not bindings:
            return None

        bp = bindings[0]
        if bp.kind not in _SIGNATURE_ALLOWED_PARAMETER_KINDS:
            raise ValueError(f'{route_path}: incompatible binding parameter {bp.name}')

        binding_name = bp.name
        parameter_names.add(binding_name)

        args = get_args(type_hints[binding_name])
        return (binding_name, binding_type if is_request_binding else args[0])

    def verify_defaults(self,
                        route_path: str,
                        parameter_names: Set[str],
                        defaults: Mapping[str, Any],
                        parameters: List[inspect.Parameter],
                        type_hints: Mapping[str, Any]) -> None:
        unused = parameter_names.intersection(defaults)
        if unused:
            raise ValueError(f'{route_path}: defaults {", ".join(unused)} not used')

        compatible = {p.name for p in parameters if p.kind in _SIGNATURE_ALLOWED_PARAMETER_KINDS}
        incompatible = frozenset(defaults) - compatible
        if incompatible:
            raise ValueError(f'{route_path}: defaults {", ".join(incompatible)} cannot used as parameters')

        # check defaults value types
        wrong_type = []
        for default_name, default_value in defaults.items():
            annotation = type_hints.get(default_name)
            if default_value is None:
                if not (get_origin(annotation) is Union and [a for a in get_args(annotation) if a is _NONE_TYPE]):
                    # None not supported
                    wrong_type.append(default_name)
            else:
                annotation = _unwrap_type_annotation(annotation)
                if not isinstance(default_value, annotation):
                    # value is of wring type
                    wrong_type.append(default_name)

        if wrong_type:
            plural = len(wrong_type) > 1
            raise ValueError(
                f'{route_path}: defaults {", ".join(wrong_type)}: incompatible type{"s" if plural else ""}'
            )

    def get_routes(self) -> Iterable[RouteDefinition]:
        def walk_children(path: List[Union[str, PathParameter]],
                          path_segment: Union[str, PathParameter],
                          entry: PathEntry) -> Iterable[RouteDefinition]:
            path.append(path_segment)
            try:
                yield from walk_route_tree(path, entry)
            finally:
                path.pop()

        def walk_route_tree(path: List[Union[str, PathParameter]], entry: PathEntry) -> Iterable[RouteDefinition]:
            if entry.methodmap:
                current_path = tuple(path)
                for method, endpoint in entry.methodmap.items():
                    yield current_path, method, endpoint

            for path_segment, subentry in entry.mapping.items():
                yield from walk_children(path, path_segment, subentry)

            parameter = entry.parameter
            if parameter is not None:
                yield from walk_children(path, parameter, parameter)

            subrouter = entry.subrouter
            if subrouter is not None:
                yield from walk_route_tree(path, subrouter.root)

        return walk_route_tree([], self.root)


def _parse_header(header: Optional[str]) -> Optional[str]:
    # pretend all header values are case-insensitive
    return header.split(';', 1)[0].strip().lower() if header else None


def _parse_header_with_quality(header: str) -> Optional[str]:
    header_parts = header.split(';')
    for parameter in header_parts[1:]:
        # XXX require positive quality value
        parts = parameter.split('=', 1)
        if len(parts) == 2 and parts[0].strip().lower() == 'q' and parts[1].strip() in _QUALITY_ZERO:
            # not acceptable
            return None

    return header_parts[0].strip().lower()


def _split_route_path(route_path: str) -> List[str]:
    path_segments = route_path.split(_PATH_SEPARATOR)
    return path_segments[1:] if route_path.startswith(_PATH_SEPARATOR) else path_segments


def _decode_url_encoded(url: Optional[str]) -> Dict[str, str]:
    if not url:
        return {}

    try:
        data = {}
        # XXX return single/first value for each parameter only
        for name, value in parse_qsl(url, strict_parsing=True):
            if name not in data:
                data[name] = value
        return data
    except ValueError as e:
        raise HTTPError(HTTPStatus.BAD_REQUEST) from e


def _is_annotated_with(hints: Any, annotation: Any) -> bool:
    if get_origin(hints) is not Annotated:
        return False

    args = get_args(hints)
    return len(args) >= 2 and not isinstance(args[0], TypeVar) and annotation in args[1:]


def _unwrap_type_annotation(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    origin = get_origin(annotation)
    if origin is Union:
        union_args = [a for a in get_args(annotation) if a is not _NONE_TYPE]
        if len(union_args) == 1:
            return union_args[0]

    return annotation
