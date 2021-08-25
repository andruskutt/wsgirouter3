"""
WSGI router.

Homepage: https://github.com/andruskutt/wsgirouter3

License: MIT
"""

import cgi
import functools
import inspect
import io
import json
import logging
import typing
from dataclasses import asdict as dataclass_asdict, dataclass, field, is_dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from types import GeneratorType
from typing import Any, Callable, Dict, Generic, Iterable, List, Mapping, Optional, Set, Tuple, TypeVar, Union
from urllib.parse import parse_qsl

__all__ = [
    'ROUTE_OPTIONS_KEY', 'ROUTE_PATH_KEY', 'ROUTE_ROUTING_ARGS_KEY',
    'HTTPError', 'MethodNotAllowedError', 'NotFoundError',
    'PathPrefixMatchingRouter', 'PathRouter', 'PathParameter',
    'Request', 'WsgiApp', 'WsgiAppConfig', 'Query', 'Body'
]

ROUTE_OPTIONS_KEY = 'route.options'
ROUTE_PATH_KEY = 'route.path'
ROUTE_ROUTING_ARGS_KEY = 'wsgiorg.routing_args'

_CONTENT_LENGTH_HEADER = 'Content-Length'
_CONTENT_TYPE_HEADER = 'Content-Type'
_CONTENT_TYPE_APPLICATION_JSON = 'application/json'
_CONTENT_TYPE_MULTIPART_FORM_DATA = 'multipart/form-data'

_WSGI_ACCEPT_HEADER = 'HTTP_ACCEPT'
_WSGI_CONTENT_LENGTH_HEADER = 'CONTENT_LENGTH'
_WSGI_CONTENT_TYPE_HEADER = 'CONTENT_TYPE'
_WSGI_PATH_INFO_HEADER = 'PATH_INFO'
_WSGI_REQUEST_METHOD_HEADER = 'REQUEST_METHOD'
_WSGI_SCRIPT_NAME_HEADER = 'SCRIPT_NAME'

_FORM_DECODE_ENVIRONMENT_KEYS = {_WSGI_CONTENT_LENGTH_HEADER, _WSGI_CONTENT_TYPE_HEADER}

_NO_DATA_BODY = b''
_NO_DATA_RESULT = _NO_DATA_BODY,

_STATUSES_WITHOUT_CONTENT = frozenset(
    (s for s in HTTPStatus if (s >= 100 and s < 200) or s in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED)),
)
_STATUS_ROW_FROM_CODE = {s.value: f'{s} {s.phrase}' for s in HTTPStatus}

_PATH_SEPARATOR = '/'

_SIGNATURE_CONTEXT_PARAMETER_KINDS = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_SIGNATURE_ALLOWED_PARAMETER_KINDS = (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)

_BOOL_TRUE_VALUES = frozenset(('1', 'true', 'yes', 'on'))
_BOOL_VALUES = frozenset(frozenset(('0', 'false', 'no', 'off')) | _BOOL_TRUE_VALUES)

_NONE_TYPE = type(None)
T = TypeVar('T')

_NO_ENDPOINT_DEFAULTS: Dict[str, Any] = {}
_NO_POSITIONAL_ARGS = ()

_logger = logging.getLogger('wsgirouter')


class cached_property:  # noqa: N801
    """
    Cached property implementation.

    Implementation without locking, see: https://bugs.python.org/issue43468
    """

    def __init__(self, func):
        self.func = func
        self.attrname = None
        self.__doc__ = func.__doc__

    def __set_name__(self, owner, name):
        if self.attrname is None:
            self.attrname = name
        elif name != self.attrname:
            raise TypeError(
                f'Cannot assign the same cached_property to two different names ({self.attrname!r} and {name!r}).'
            )

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self.attrname is None:
            raise TypeError('Cannot use cached_property instance without calling __set_name__ on it.')

        value = self.func(instance)
        instance.__dict__[self.attrname] = value
        return value


class HTTPError(Exception):
    def __init__(self, status: HTTPStatus, result=None, headers: Optional[dict] = None) -> None:
        self.status = status
        self.result = status.description if result is None and status not in _STATUSES_WITHOUT_CONTENT else result
        self.headers = headers


class NotFoundError(HTTPError):
    def __init__(self, path_info: str) -> None:
        super().__init__(HTTPStatus.NOT_FOUND)
        self.path_info = path_info


class MethodNotAllowedError(HTTPError):
    def __init__(self, allowed: Iterable[str]) -> None:
        super().__init__(HTTPStatus.METHOD_NOT_ALLOWED, headers={'Allow': ', '.join(allowed)})
        self.allowed = frozenset(allowed)


class Request:
    def __init__(self, config: 'WsgiAppConfig', environ: dict) -> None:
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

        max_content_length = self.config.max_content_length
        if max_content_length is not None and max_content_length < content_length:
            raise HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

        return self.environ['wsgi.input'].read(content_length)

    @cached_property
    def form(self) -> Mapping:
        if self.content_type != _CONTENT_TYPE_MULTIPART_FORM_DATA:
            raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        if not _FORM_DECODE_ENVIRONMENT_KEYS.issubset(self.environ):
            raise HTTPError(HTTPStatus.BAD_REQUEST)

        sandbox = {k: self.environ[k] for k in _FORM_DECODE_ENVIRONMENT_KEYS}
        sandbox[_WSGI_REQUEST_METHOD_HEADER] = 'POST'
        try:
            # PEP-594: cgi module will be removed in python 3.10
            return cgi.FieldStorage(fp=io.BytesIO(self.body), environ=sandbox, strict_parsing=True)
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def json(self):
        if self.content_type != _CONTENT_TYPE_APPLICATION_JSON:
            raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        try:
            return self.config.json_deserializer(self.body)
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def query_parameters(self) -> dict:
        qs = self.environ.get('QUERY_STRING')
        if not qs:
            return {}

        try:
            data = {}
            # XXX return single/first value for each parameter only
            for name, value in parse_qsl(qs, strict_parsing=True):
                if name not in data:
                    data[name] = value
            return data
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def method(self) -> str:
        return self.environ[_WSGI_REQUEST_METHOD_HEADER]


def _default_binder(data, result_type):
    if not isinstance(data, result_type):
        raise HTTPError(HTTPStatus.BAD_REQUEST)

    return data


def _json_result_handler(config: 'WsgiAppConfig', result, headers: dict) -> Tuple[bytes]:
    response = config.json_serializer(result)
    headers.setdefault(_CONTENT_TYPE_HEADER, _CONTENT_TYPE_APPLICATION_JSON)
    headers[_CONTENT_LENGTH_HEADER] = str(len(response))
    return response,


def _custom_result_handler(config: 'WsgiAppConfig', result, headers: dict) -> Iterable:
    for matcher, handler in config.result_converters:
        if matcher(result):
            return handler(result, headers)

    # dataclass is json if not overridden by custom converter
    if not is_dataclass(result):
        raise ValueError(f'Unknown result {result}')

    return _json_result_handler(config, dataclass_asdict(result), headers)


def _default_result_handler(config: 'WsgiAppConfig', environ: dict, result) -> Tuple[int, Iterable, dict]:
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
            raise ValueError(f'Unexpected result {result} for {status.phrase} response')

        result = _NO_DATA_RESULT
    elif isinstance(result, dict):
        result = _json_result_handler(config, result, headers)
    elif isinstance(result, bytes):
        if _CONTENT_TYPE_HEADER not in headers:
            raise ValueError('Unknown content type for binary result')

        result = result,
        headers[_CONTENT_LENGTH_HEADER] = str(len(result[0]))
    elif isinstance(result, str):
        result = result.encode(),
        headers.setdefault(_CONTENT_TYPE_HEADER, config.default_str_content_type)
        headers[_CONTENT_LENGTH_HEADER] = str(len(result[0]))
    elif not isinstance(result, GeneratorType):
        result = _custom_result_handler(config, result, headers)

    return status, result, headers


def _default_error_handler(config: 'WsgiAppConfig', environ: dict, exc: Exception) -> tuple:
    if not isinstance(exc, HTTPError):
        config.logger.exception('Unhandled exception', exc_info=exc)

        exc = HTTPError(HTTPStatus.INTERNAL_SERVER_ERROR)

    return exc.status, exc.result, exc.headers or {}


def _json_dumps_adapter(obj: Any) -> bytes:
    # always utf-8: https://tools.ietf.org/html/rfc8259#section-8.1
    return json.dumps(obj).encode()


@dataclass
class WsgiAppConfig:
    json_deserializer: Callable[[bytes], Any] = staticmethod(json.loads)
    json_serializer: Callable[[Any], bytes] = staticmethod(_json_dumps_adapter)
    before_request: Optional[Callable[[Any], None]] = None
    after_request: Optional[Callable[[int, dict, dict], None]] = None
    request_factory: Callable[['WsgiAppConfig', dict], Any] = Request
    binder: Callable[[Any, Any], Any] = staticmethod(_default_binder)
    result_handler: Callable[['WsgiAppConfig', dict, Any],
                             Tuple[int, Iterable, dict]] = staticmethod(_default_result_handler)
    result_converters: List[Tuple[Callable[[Any], bool], Callable[[Any, dict], Iterable]]] = field(default_factory=list)
    default_str_content_type: str = 'text/plain;charset=utf-8'
    error_handler: Callable[['WsgiAppConfig', dict, Exception], Any] = staticmethod(_default_error_handler)
    logger: Union[logging.Logger, logging.LoggerAdapter] = _logger
    max_content_length: Optional[int] = None


class WsgiApp:
    def __init__(self,
                 router: Callable[[dict], Callable],
                 config: Optional[WsgiAppConfig] = None) -> None:
        self.router = router
        self.config = config or WsgiAppConfig()

    def __call__(self, environ: Dict[str, Any], start_response: Callable) -> Iterable:
        try:
            handler = self.router(environ)

            request = self.config.request_factory(self.config, environ)
            before_request = self.config.before_request
            if before_request is not None:
                before_request(request)

            result = handler(request, **environ[ROUTE_ROUTING_ARGS_KEY][1])
        except Exception as exc:  # noqa: B902
            result = self.config.error_handler(self.config, environ, exc)

        # XXX error handling for result conversion and after request hook
        status, result, response_headers = self.config.result_handler(self.config, environ, result)

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


class Endpoint:
    __slots__ = (
        'handler', 'defaults', 'options', 'route_path', 'consumes', 'produces', 'query_binding', 'body_binding'
    )

    def __init__(self, handler: Callable, defaults: Optional[dict], options: Any, route_path: str,
                 consumes: Optional[str], produces: Optional[str],
                 query_binding: Optional[Tuple[str, Any]], body_binding: Optional[Tuple[str, Any]]) -> None:
        self.handler = handler
        self.defaults = dict(defaults) if defaults else _NO_ENDPOINT_DEFAULTS
        self.options = options
        self.route_path = route_path
        self.consumes = consumes
        self.produces = produces
        self.query_binding = query_binding
        self.body_binding = body_binding

        if query_binding is not None or body_binding is not None:
            @functools.wraps(handler)
            def binding_handler(request, *args, **kwargs):
                if query_binding:
                    data = request.query_parameters
                    kwargs[query_binding[0]] = request.config.binder(data, query_binding[1])

                if body_binding:
                    if request.content_type == _CONTENT_TYPE_APPLICATION_JSON:
                        data = request.json
                    elif request.content_type == _CONTENT_TYPE_MULTIPART_FORM_DATA:
                        data = request.form
                    else:
                        raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

                    kwargs[body_binding[0]] = request.config.binder(data, body_binding[1])

                return handler(request, *args, **kwargs)

            self.handler = binding_handler


class PathEntry:
    __slots__ = ('mapping', 'parameter', 'methodmap')

    def __init__(self) -> None:
        self.mapping: Dict[str, 'PathEntry'] = {}
        self.parameter: Optional['PathParameter'] = None
        self.methodmap: Dict[str, Endpoint] = {}

    def __getitem__(self, path_segment: str) -> 'PathEntry':
        handler = self.mapping.get(path_segment)
        if handler is not None:
            return handler

        if self.parameter is not None and self.parameter.match(path_segment):
            return self.parameter

        # no match
        raise KeyError

    def add_endpoint(self, methods: Iterable[str], endpoint: Endpoint) -> None:
        self.methodmap.update(dict.fromkeys(methods, endpoint))


class Query(Generic[T]):
    pass


class Body(Generic[T]):
    pass


class PathParameter(PathEntry):
    __slots__ = ('name',)

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class BoolPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        return path_segment in _BOOL_VALUES

    def accept(self, kwargs: dict, path_segment: str) -> None:
        kwargs[self.name] = path_segment in _BOOL_TRUE_VALUES


class IntPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        return bool(path_segment and (path_segment[1:] if path_segment[0] == '-' else path_segment).isdigit())

    def accept(self, kwargs: dict, path_segment: str) -> None:
        kwargs[self.name] = int(path_segment)


class StringPathParameter(PathParameter):

    def match(self, path_segment: str) -> bool:
        # do not allow zero-length strings
        return bool(path_segment)

    def accept(self, kwargs: dict, path_segment: str) -> None:
        # XXX should decode path segment?
        kwargs[self.name] = path_segment


# duplicate definitions by PEP-563
_DEFAULT_PARAMETER_TYPE_MAP = {
    'bool': BoolPathParameter,
    'int': IntPathParameter,
    'str': StringPathParameter,
    bool: BoolPathParameter,
    int: IntPathParameter,
    str: StringPathParameter,
}


class PathRouter:
    # environ keys for routing data
    options_key: str = ROUTE_OPTIONS_KEY
    path_key: str = ROUTE_PATH_KEY
    routing_args_key: str = ROUTE_ROUTING_ARGS_KEY
    # path parameter markers, by default RFC 6570 level 1
    path_parameter_start: str = '{'
    path_parameter_end: Optional[str] = '}'

    def __init__(self) -> None:
        self.root = PathEntry()
        self.parameter_types = _DEFAULT_PARAMETER_TYPE_MAP.copy()
        self.default_options = None

    def __call__(self, environ: Dict[str, Any]) -> Callable:
        """Route resolver."""
        entry = self.root
        path_args: Dict[str, Any] = {}
        route_path = environ.get(_WSGI_PATH_INFO_HEADER)
        if route_path and route_path != _PATH_SEPARATOR:
            try:
                for path_segment in _split_route_path(route_path):
                    entry = entry[path_segment]
                    if isinstance(entry, PathParameter):
                        entry.accept(path_args, path_segment)
            except KeyError:
                raise NotFoundError(route_path) from None

        if not entry.methodmap:
            # intermediate path segment, no endpoints defined
            raise NotFoundError(route_path)

        endpoint = self.negotiate_endpoint(environ, entry)

        environ[self.options_key] = endpoint.options
        environ[self.path_key] = endpoint.route_path
        environ[self.routing_args_key] = (_NO_POSITIONAL_ARGS, {**endpoint.defaults, **path_args})
        return endpoint.handler

    def negotiate_endpoint(self, environ: Dict[str, Any], entry: PathEntry) -> Endpoint:
        method = environ[_WSGI_REQUEST_METHOD_HEADER]
        try:
            endpoint = entry.methodmap[method]
        except KeyError:
            raise MethodNotAllowedError(tuple(entry.methodmap.keys())) from None

        required_content_type = endpoint.consumes
        if required_content_type:
            actual_content_type = _parse_header(environ.get(_WSGI_CONTENT_TYPE_HEADER))
            if actual_content_type != required_content_type:
                raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        accepted_media_ranges = environ.get(_WSGI_ACCEPT_HEADER)
        if accepted_media_ranges:
            response_content_type = endpoint.produces
            if response_content_type:
                for ct in accepted_media_ranges.split(','):
                    media_range = _parse_header(ct.lstrip())
                    # XXX partial media range support: type/*
                    if response_content_type == media_range or media_range == '*/*':
                        break
                else:
                    raise HTTPError(HTTPStatus.NOT_ACCEPTABLE)

        return endpoint

    def route(self,
              route_path: str,
              methods: Iterable[str],
              defaults: Optional[dict] = None,
              options: Any = None,
              consumes: Optional[str] = None,
              produces: Optional[str] = None) -> Callable:
        def wrapper(handler):
            self.add_route(route_path, methods, handler, defaults, options, consumes, produces)
            return handler

        return wrapper

    def add_route(self,
                  route_path: str,
                  methods: Iterable[str],
                  handler: Callable,
                  defaults: Optional[dict] = None,
                  options: Any = None,
                  consumes: Optional[str] = None,
                  produces: Optional[str] = None) -> None:
        if not methods:
            raise ValueError(f'{route_path}: no methods defined')

        signature = inspect.signature(handler)
        entry, parameter_names = self.parse_route_path(route_path, signature)

        handler_parameters = list(signature.parameters.values())
        if not handler_parameters:
            raise ValueError(f'{route_path}: missing context parameter')

        # skip first parameter (request handling context)
        context_parameter = handler_parameters.pop(0)
        if context_parameter.kind not in _SIGNATURE_CONTEXT_PARAMETER_KINDS:
            raise ValueError(f'{route_path}: incompatible context parameter {context_parameter.name}')

        query_binding = self.get_binding_parameter(route_path, parameter_names, handler_parameters, Query)
        body_binding = self.get_binding_parameter(route_path, parameter_names, handler_parameters, Body)

        if defaults is not None:
            compatible = {p.name for p in handler_parameters if p.kind in _SIGNATURE_ALLOWED_PARAMETER_KINDS}
            incompatible = frozenset(defaults) - compatible
            if incompatible:
                raise ValueError(f'{route_path}: defaults {", ".join(incompatible)} cannot used as parameters')

        # check that all handler parameters are set or have default values
        required_parameters = {p.name for p in handler_parameters
                               if p.kind in _SIGNATURE_ALLOWED_PARAMETER_KINDS and p.default is inspect.Parameter.empty}

        missing_parameters = required_parameters - parameter_names
        if defaults is not None:
            missing_parameters = missing_parameters - defaults.keys()
        if missing_parameters:
            raise ValueError(f'{route_path}: parameters {", ".join(missing_parameters)} are not initialized')

        existing = set(methods) & entry.methodmap.keys()
        if existing:
            raise ValueError(f'{route_path}: redefinition of handler for method(s) {", ".join(existing)}')

        route_options = self.default_options if options is None else options
        endpoint = Endpoint(
            handler, defaults, route_options, route_path, consumes, produces, query_binding, body_binding
        )
        entry.add_endpoint(methods, endpoint)

    def parse_route_path(self, route_path: str, signature: inspect.Signature) -> Tuple[PathEntry, set]:
        entry = self.root
        parameter_names: Set[str] = set()

        if route_path == _PATH_SEPARATOR:
            return entry, parameter_names

        for path_segment in _split_route_path(route_path):
            if not path_segment:
                raise ValueError(f'{route_path}: missing path segment')
            elif path_segment.startswith(self.path_parameter_start):
                # path parameter definition
                factory, parameter_name = self.parse_parameter(path_segment, route_path, signature)
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

    def parse_parameter(self, parameter: str, route_path: str, signature: inspect.Signature) -> Tuple[Callable, str]:
        suffix_length = -len(self.path_parameter_end) if self.path_parameter_end else None
        parameter_name = parameter[len(self.path_parameter_start):suffix_length]
        if not ((not suffix_length or parameter.endswith(self.path_parameter_end)) and parameter_name):
            raise ValueError(f'{route_path}: invalid path parameter definition {parameter}')

        try:
            parameter_signature = signature.parameters[parameter_name]
        except KeyError:
            raise ValueError(f'{route_path}: path parameter {parameter_name} not defined in handler') from None

        if parameter_signature.kind not in _SIGNATURE_ALLOWED_PARAMETER_KINDS:
            raise ValueError(f'{route_path}: path parameter {parameter_name} value passing by keyword not supported')

        annotation = parameter_signature.annotation
        if annotation == inspect.Parameter.empty:
            raise ValueError(f'{route_path}: path parameter {parameter_name} missing type annotation')

        # unwrap possible Optional[x]/Union[x, None]
        origin = typing.get_origin(annotation)
        if origin is Union:
            union_args = typing.get_args(annotation)
            if len(union_args) == 2 and union_args[1] is _NONE_TYPE:
                annotation = union_args[0]

        try:
            factory = self.parameter_types[annotation]
        except KeyError:
            raise ValueError(f'{route_path}: unknown path parameter {parameter_name} type {annotation}') from None

        return factory, parameter_name

    def get_binding_parameter(self,
                              route_path: str,
                              parameter_names: Set[str],
                              parameters: list,
                              binding_type) -> Optional[Tuple[str, Any]]:
        bindings = [p for p in parameters if typing.get_origin(p.annotation) is binding_type]
        if len(bindings) > 1:
            raise ValueError(f'{route_path}: too many {binding_type.__name__}[] annotated parameters')

        if not bindings:
            return None

        bp = bindings[0]
        if bp.kind not in _SIGNATURE_ALLOWED_PARAMETER_KINDS:
            raise ValueError(f'{route_path}: incompatible binding parameter {bp.name}')

        binding_name = bp.name
        parameter_names.add(binding_name)

        return (binding_name, typing.get_args(bp.annotation)[0])


class PathPrefixMatchingRouter:
    def __init__(self, mapping: Dict[str, Callable]) -> None:
        self.mapping: List[Tuple[str, str, Callable]] = []
        self.add_route_mapping(mapping)

    def __call__(self, environ: Dict[str, Any]) -> Callable:
        route_path = environ.get(_WSGI_PATH_INFO_HEADER) or _PATH_SEPARATOR
        for match, prefix, subrouter in self.mapping:
            if route_path.startswith(match):
                environ[_WSGI_SCRIPT_NAME_HEADER] = environ.get(_WSGI_SCRIPT_NAME_HEADER, '') + prefix
                environ[_WSGI_PATH_INFO_HEADER] = route_path[len(prefix):]
                return subrouter(environ)

        raise NotFoundError(route_path)

    def add_route(self, prefix: str, handler: Callable) -> None:
        if not prefix or prefix == _PATH_SEPARATOR:
            raise ValueError(f'Invalid path prefix {prefix}')

        matchingprefix = prefix
        if not prefix.endswith(_PATH_SEPARATOR):
            matchingprefix += _PATH_SEPARATOR
        else:
            prefix = prefix[:-len(_PATH_SEPARATOR)]

        if matchingprefix in (r[0] for r in self.mapping):
            raise ValueError(f'Duplicate prefix {prefix}')

        self.mapping.append((matchingprefix, prefix, handler))

    def add_route_mapping(self, mapping: Dict[str, Callable]) -> None:
        for prefix, handler in mapping.items():
            self.add_route(prefix, handler)


def _parse_header(header: Optional[str]) -> Optional[str]:
    # pretend all header values are case-insensitive
    return header.split(';', 1)[0].strip().lower() if header else None


def _split_route_path(route_path: str) -> list:
    path_segments = route_path.split(_PATH_SEPARATOR)
    return path_segments[1:] if route_path.startswith(_PATH_SEPARATOR) else path_segments
