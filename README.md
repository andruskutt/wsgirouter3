# wsgirouter3

Small opinionated WSGI request dispatcher. Influenced by Flask.

Works using path segments instead of more common regex matching (RFC 3986 path segment parameters are not supported) https://datatracker.ietf.org/doc/html/rfc3986#section-3.3

Path variables are by default defined using RFC 6570 level 1 https://datatracker.ietf.org/doc/html/rfc6570#section-1.2 Start and optional end markers are customizable.
Path variable types are defined using python typing information. Customizable, types supported out-of-box: bool, int, str.

WSGI environ wrapper can passed to handler if there is parameter with type Request. No global variables/threadlocals.
Request body and query string binding is also supported, using generic types Body and Query.

Supports overlapping path segments: zero or more literal segments can overlap with one parameter definition. Parameters of different type and/or name in same position are not supported. Literal segment takes precedence.


```python
@router.route('/abc/literal', methods=('GET',))
def literal():
    pass

@router.route('/abc/{variable}', methods=('GET',))
def parametrized(variable: str):
    pass
```

Multiple routes can point to same handler:

```python
@router.route('/abc', methods=('GET',), defaults={'variable': None})
@router.route('/abc/{variable}', methods=('GET',))
def parametrized(variable: Optional[str]):
    pass
```

Content negotiation:

```python
@router.route('/get', methods=('GET',), produces='application/json')
def get() -> dict:
    return {'field': 'value'}

@router.route('/post', methods=('POST',), consumes='application/json')
def post_with_json(req: Request) -> Tuple[int]:
    data = req.json
    return 204,
```

Query string and request body binding:

```python
@router.route('/get', methods=('GET',), produces='application/json')
def get(query: Query[dict]) -> dict:
    return query

@router.route('/post', methods=('POST',), consumes='application/json')
def post_with_json(data: Body[dict]) -> Tuple[int]:
    # do something with data
    return 204,
```

Return type handling:

| Type | Description |
| ---- | ----------- |
| tuple | shortcut for returning status code and optional result + headers |
| None | allowed for status codes which have no content |
| dict | application/json |
| str | defined by optional Content-Type header. When header is missing, taken from config.default_str_content_type, by default text/plain;charset=utf-8 |
| bytes | defined by required Content-Type header |
| dataclass | application/json, but overridable by custom result handler |
| typing.GeneratorType | passed as is |

## Configuration checklist

WsgiAppConfig class

| Task | Action |
| ----------- | ----------- |
| Want to use another json library or configure value types serialized / deserialized | Override json_serializer / json_deserializer |
| Change maximum length of accepted request body | Set value of max_content_length |
| Change default content type for str returned | Change value of default_str_content_type |
| Add authorization | Set before_request hook handler, use route options to define roles. See [sample](examples/authorization/application.py) |
| Handle more return types | Add entry of tuple[matcher, handler] to result_converters or override custom_result_handler |
| Validate/convert query string and request body | Use Query and Body generics with value class in handler and override binder |
| Customize error handling | Override error_handler |

PathRouter class

| Task | Action |
| ----------- | ----------- |
| Change parameter markers | Change value of path_parameter_start and path_parameter_end |
| Add new path parameter type | Add new class inherited from PathParameter into parameter_types |

## python 3.7

Monkeypatching of typing module is required. See [tests/conftest.py](tests/conftest.py)
