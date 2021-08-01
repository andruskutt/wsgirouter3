# wsgirouter3

Small opinionated WSGI request dispatcher. Influenced by Flask.

Works using path segments instead of more common regex matching (RFC 3986 path segment parameters are not supported) https://datatracker.ietf.org/doc/html/rfc3986#section-3.3

Path variables are by default defined using RFC 6570 level 1 https://datatracker.ietf.org/doc/html/rfc6570#section-1.2 Start and optional end markers are customizable.
Path variable types are defined using python typing information. Customizable, types supported out-of-box: bool, int, str.

Request context (by default WSGI environ wrapper) is passed as handler's first positional parameter.

Supports overlapping path segments: zero or more literal segments with optional parameter. Parameters of different type in same position are not supported. Literal segment takes precedence.


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
def parametrized(req, variable: str):
    pass
```

## python 3.7

Monkeypatching of typing module is required. See [tests/conftest.py](tests/conftest.py)
