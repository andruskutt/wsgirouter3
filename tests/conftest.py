"""Test setup."""

try:
    import typing
    # available starting python 3.8
    typing.get_origin(None)
    typing.get_args(None)
except AttributeError:
    typing.get_origin = lambda tp: getattr(tp, '__origin__', None)
    typing.get_args = lambda tp: getattr(tp, '__args__', ())
