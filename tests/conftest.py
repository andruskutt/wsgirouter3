"""Test setup."""

try:
    # available starting python 3.8
    from functools import cached_property  # type: ignore
except ImportError:
    from backports.cached_property import cached_property
    import functools
    functools.cached_property = cached_property

try:
    import typing
    # available starting python 3.8
    typing.get_origin(None)
    typing.get_args(None)
except AttributeError:
    typing.get_origin = lambda tp: getattr(tp, '__origin__', None)
    typing.get_args = lambda tp: getattr(tp, '__args__', ())
