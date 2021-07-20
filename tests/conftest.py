"""Test setup."""

try:
    # available starting python 3.8
    from functools import cached_property  # type: ignore
except ImportError:
    from backports.cached_property import cached_property
    import functools
    functools.cached_property = cached_property
