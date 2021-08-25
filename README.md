# wsgirouter3

Small opinionated WSGI request dispatcher. Influenced by Flask.

Works using path segments instead of more common regex matching (RFC 3986 path segment parameters are not supported) https://datatracker.ietf.org/doc/html/rfc3986#section-3.3

Path variables are by default defined using RFC 6570 level 1 https://datatracker.ietf.org/doc/html/rfc6570#section-1.2 Start and optional end markers are customizable.
Path variable types are defined using python typing information. Customizable, types supported out-of-box: bool, int, str.

Request context is passed as handler's first positional parameter. No global variables/threadlocals. Context factory is customizable, by default minimal WSGI environ wrapper.

Supports overlapping path segments: zero or more literal segments can overlap with one parameter definition. Parameters of different type and/or name in same position are not supported. Literal segment takes precedence.


```python
@router.route('/abc/literal', methods=('GET',))
def literal(req):
    pass

@router.route('/abc/{variable}', methods=('GET',))
def parametrized(req, variable: str):
    pass
```

Multiple routes can point to same handler:

```python
@router.route('/abc', methods=('GET',), defaults={'variable': None})
@router.route('/abc/{variable}', methods=('GET',))
def parametrized(req, variable: Optional[str]):
    pass
```

Content negotiation:

```python
@router.route('/get', methods=('GET',), produces='application/json')
def get(req) -> dict:
    return {'field': 'value'}

@router.route('/post', methods=('POST',), consumes='application/json')
def post_with_json(req) -> Tuple[int]:
    data = req.json
    return 204,
```

Query string and request body binding:

```python
@router.route('/get', methods=('GET',), produces='application/json')
def get(req, query: Query[dict]) -> dict:
    return query

@router.route('/post', methods=('POST',), consumes='application/json')
def post_with_json(req, data: Body[dict]) -> Tuple[int]:
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

## python 3.7

Monkeypatching of typing module is required. See [tests/conftest.py](tests/conftest.py)
