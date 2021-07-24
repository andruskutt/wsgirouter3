"""WSGI router."""

import cgi
import inspect
import io
import json
import logging
from dataclasses import dataclass, is_dataclass
from functools import cached_property
from http import HTTPStatus
from http.cookies import SimpleCookie
from types import GeneratorType
from typing import Any, Callable, Dict, Iterable, List, Mapping, NoReturn, Optional, Tuple, Type, Union
from urllib.parse import parse_qs


__all__ = [
    'ROUTE_OPTIONS_KEY', 'ROUTE_PATH_KEY', 'ROUTE_ROUTING_ARGS_KEY',
    'HTTPError', 'MethodNotAllowedError', 'NotFoundError',
    'PathPrefixMatchingRouter', 'PathRouter', 'PathParameter',
    'Request', 'WsgiApp', 'WsgiAppConfig'
]

ROUTE_OPTIONS_KEY = 'route.options'
ROUTE_PATH_KEY = 'route.path'
ROUTE_ROUTING_ARGS_KEY = 'wsgiorg.routing_args'

_CONTENT_LENGTH_HEADER = 'Content-Length'
_CONTENT_TYPE_HEADER = 'Content-Type'
_CONTENT_TYPE_APPLICATION_JSON = 'application/json'
_CONTENT_TYPE_MULTIPART_FORM_DATA = 'multipart/form-data'

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
_STATUS_ROW_MAP = {s.value: f'{s} {s.phrase}' for s in HTTPStatus}

_PATH_SEPARATOR = '/'

_SIGNATURE_ALLOWED_PARAMETER_KINDS = (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)

_BOOL_TRUE_VALUES = frozenset(('1', 'true', 'yes', 'on'))
_BOOL_VALUES = frozenset(frozenset(('0', 'false', 'no', 'off')) | _BOOL_TRUE_VALUES)

_NO_ENDPOINT_DEFAULTS = {}
_NO_POSITIONAL_ARGS = ()

_logger = logging.getLogger('wsgirouter')


class HTTPError(Exception):
    def __init__(self, status: HTTPStatus, result=None, headers: Optional[dict] = None) -> None:
        self.status = status
        self.result = status.description if result is None else result
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
        return self._parse_header(self.environ.get(_WSGI_CONTENT_TYPE_HEADER))

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

        # XXX optionally check maximum length
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
            return json.loads(self.body, cls=self.config.json_decoder)
        except json.JSONDecodeError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def query_parameters(self) -> dict:
        qs = self.environ.get('QUERY_STRING')
        if not qs:
            return {}

        try:
            data = parse_qs(qs, strict_parsing=True)
            # return single/first value for each parameter
            return {k: v[0] for k, v in data.items()}
        except ValueError as e:
            raise HTTPError(HTTPStatus.BAD_REQUEST) from e

    @cached_property
    def method(self) -> str:
        return self.environ[_WSGI_REQUEST_METHOD_HEADER]

    def _parse_header(self, header: Optional[str]) -> Optional[str]:
        # pretend all header values are case-insensitive
        return header.split(';', 1)[0].strip().lower() if header else None


def _default_result_converter(config: 'WsgiAppConfig', environ: dict, result) -> Tuple[int, Iterable, dict]:
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
    elif isinstance(result, dict) or is_dataclass(result):
        # https://tools.ietf.org/html/rfc4627
        result = json.dumps(result, cls=config.json_encoder).encode('utf-8'),
        headers[_CONTENT_TYPE_HEADER] = _CONTENT_TYPE_APPLICATION_JSON
        headers[_CONTENT_LENGTH_HEADER] = str(len(result[0]))
    elif isinstance(result, bytes):
        if _CONTENT_TYPE_HEADER not in headers:
            raise ValueError('Unknown content type for binary result')

        result = result,
        headers[_CONTENT_LENGTH_HEADER] = str(len(result[0]))
    elif isinstance(result, str):
        if _CONTENT_TYPE_HEADER not in headers:
            headers[_CONTENT_TYPE_HEADER] = 'text/plain'

        result = result.encode('utf-8'),
        headers[_CONTENT_LENGTH_HEADER] = str(len(result[0]))
    elif not isinstance(result, GeneratorType):
        raise ValueError(f'Unknown result {result}')

    return status, result, headers


def _default_error_handler(config: 'WsgiAppConfig', environ: dict, exc: Exception) -> tuple:
    if not isinstance(exc, HTTPError):
        config.logger.exception('Unhandled exception', exc_info=exc)

        exc = HTTPError(HTTPStatus.INTERNAL_SERVER_ERROR)

    return exc.status, exc.result, exc.headers or {}


@dataclass
class WsgiAppConfig:
    json_decoder: Optional[Type[json.JSONDecoder]] = None
    json_encoder: Optional[Type[json.JSONEncoder]] = None
    before_request: Optional[Callable[[Any], None]] = None
    after_request: Optional[Callable[[int, dict, dict], None]] = None
    request_factory: Callable[['WsgiAppConfig', dict], Any] = Request
    result_converter: Callable[['WsgiAppConfig', dict, Any],
                               Tuple[int, Iterable, dict]] = staticmethod(_default_result_converter)
    error_handler: Callable[['WsgiAppConfig', dict, Exception], Any] = staticmethod(_default_error_handler)
    logger: Union[logging.Logger, logging.LoggerAdapter] = _logger


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
        status, result, response_headers = self.config.result_converter(self.config, environ, result)

        after_request = self.config.after_request
        if after_request is not None:
            after_request(status, response_headers, environ)

        if environ[_WSGI_REQUEST_METHOD_HEADER] == 'HEAD':
            # XXX close possible file-like object in result
            result_close = getattr(result, 'close', None)
            if result_close is not None:
                result_close()
            result = _NO_DATA_RESULT

        start_response(_STATUS_ROW_MAP[status], [*response_headers.items()])
        return result


class Endpoint:
    __slots__ = ('handler', 'defaults', 'options', 'route_path')

    def __init__(self, handler: Callable, defaults: Optional[dict], options: Any, route_path: str) -> None:
        self.handler = handler
        self.defaults = dict(defaults) if defaults else _NO_ENDPOINT_DEFAULTS
        self.options = options
        self.route_path = route_path


class PathEntry:
    __slots__ = ('mapping', 'parameter', 'methodmap')

    def __init__(self) -> None:
        self.mapping: Dict[str, 'PathEntry'] = {}
        self.parameter = None
        self.methodmap: Dict[str, Endpoint] = {}

    def __getitem__(self, route_path_item: str) -> 'PathEntry':
        handler = self.mapping.get(route_path_item)
        if handler is not None:
            return handler

        if self.parameter is not None and self.parameter.match(route_path_item):
            return self.parameter

        # no match
        raise KeyError

    def add_endpoint(self, methods: Iterable[str], endpoint: Endpoint) -> None:
        self.methodmap.update(dict.fromkeys(methods, endpoint))


class PathParameter(PathEntry):
    __slots__ = ('name',)

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class BoolPathParameter(PathParameter):

    def match(self, route_path_item: str) -> bool:
        return route_path_item in _BOOL_VALUES

    def accept(self, kwargs: dict, route_path_item: str) -> None:
        kwargs[self.name] = route_path_item in _BOOL_TRUE_VALUES


class IntPathParameter(PathParameter):

    def match(self, route_path_item: str) -> bool:
        return bool(route_path_item and route_path_item.isdigit())

    def accept(self, kwargs: dict, route_path_item: str) -> None:
        kwargs[self.name] = int(route_path_item)


class StringPathParameter(PathParameter):

    def match(self, route_path_item: str) -> bool:
        # do not allow zero-length strings
        return bool(route_path_item)

    def accept(self, kwargs: dict, route_path_item: str) -> None:
        # XXX should decode path segment?
        kwargs[self.name] = route_path_item


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
        kwargs = {}
        route_path = environ.get(_WSGI_PATH_INFO_HEADER)
        if route_path and route_path != _PATH_SEPARATOR:
            try:
                for route_path_item in _split_route_path(route_path):
                    entry = entry[route_path_item]
                    if isinstance(entry, PathParameter):
                        entry.accept(kwargs, route_path_item)
            except KeyError:
                raise NotFoundError(route_path) from None

        method = environ[_WSGI_REQUEST_METHOD_HEADER]
        try:
            endpoint = entry.methodmap[method]
        except KeyError:
            endpoint = self.handle_unknown_method(environ, entry)

        environ[self.options_key] = endpoint.options
        environ[self.path_key] = endpoint.route_path
        environ[self.routing_args_key] = (_NO_POSITIONAL_ARGS, {**endpoint.defaults, **kwargs})
        return endpoint.handler

    def handle_unknown_method(self, environ: Dict[str, Any], entry: PathEntry) -> NoReturn:
        raise MethodNotAllowedError(tuple(entry.methodmap.keys())) from None

    def route(self,
              route_path: str,
              methods: Iterable[str],
              defaults: Optional[dict] = None,
              options: Any = None):
        def wrapper(handler):
            self.add_route(route_path, methods, handler, defaults, options)
            return handler

        return wrapper

    def add_route(self,
                  route_path: str,
                  methods: Iterable[str],
                  handler: Callable,
                  defaults: Optional[dict] = None,
                  options: Any = None) -> None:
        if not methods:
            raise ValueError(f'{route_path}: no methods defined')

        signature = inspect.signature(handler)
        entry = self.parse_route_path(route_path, signature) if route_path != _PATH_SEPARATOR else self.root
        if defaults is not None:
            compatible = {n for n, p in signature.parameters.items() if p.kind in _SIGNATURE_ALLOWED_PARAMETER_KINDS}
            missing = frozenset(defaults) - compatible
            if missing:
                raise ValueError(f'{route_path}: defaults {", ".join(missing)} cannot used as keyword arguments')

        existing = set(methods) & entry.methodmap.keys()
        if existing:
            raise ValueError(f'{route_path}: redefinition of handler for method(s) {", ".join(existing)}')

        route_options = self.default_options if options is None else options
        entry.add_endpoint(methods, Endpoint(handler, defaults, route_options, route_path))

    def parse_route_path(self, route_path: str, signature) -> PathEntry:
        entry = self.root
        parameter_names = set()
        for rp in _split_route_path(route_path):
            if not rp:
                raise ValueError(f'{route_path}: missing path segment')
            elif rp.startswith(self.path_parameter_start):
                # path parameter definition
                factory, parameter_name = self.parse_parameter(rp, route_path, signature)
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
                mappingentry = entry.mapping.get(rp)
                if mappingentry is None:
                    entry.mapping[rp] = mappingentry = PathEntry()

                entry = mappingentry

        return entry

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

        try:
            factory = self.parameter_types[annotation]
        except KeyError:
            raise ValueError(f'{route_path}: unknown path parameter {parameter_name} type {annotation}') from None

        return factory, parameter_name


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


def _split_route_path(route_path: str) -> list:
    route_path_parts = route_path.split(_PATH_SEPARATOR)
    return route_path_parts[1:] if route_path.startswith(_PATH_SEPARATOR) else route_path_parts
