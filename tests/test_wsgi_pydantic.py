"""Tests for parameter binding using pydantic."""

import datetime
import io
import json
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, ValidationError

from wsgirouter3 import Body, HTTPError, PathRouter, WsgiApp


class ArtistSchema(BaseModel):
    name: str


class AlbumSchema(BaseModel):
    title: str
    release_date: datetime.date
    artist: ArtistSchema


def binder(data, result_type):
    if not isinstance(data, dict):
        raise HTTPError(HTTPStatus.BAD_REQUEST)

    try:
        return result_type(**data)
    except ValidationError as e:
        raise HTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {'_errors': [{'loc': e['loc'], 'type': e['type']} for e in e.errors()]}
        ) from None


def json_serializer(obj: Any) -> bytes:
    return json.dumps(obj, default=str).encode()


def start_response(status, headers):
    pass


def endpoint(body: Body[AlbumSchema]) -> dict:
    return body.model_dump()


def test_body_binding_json():
    url = '/url'
    json_bytes = b'{"title": "Title", "release_date": "2014-08-17", "artist": {"name": "Name"}}'
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()
    router.post(url)(endpoint)

    app = WsgiApp(router)
    app.config.binder = binder
    app.config.json_serializer = json_serializer

    response = b''.join(app(env, start_response))
    assert json.loads(response) == json.loads(json_bytes)


def test_body_binding_invalid_value_json():
    url = '/url'
    json_bytes = b'{"title": "Title", "release_date": "invalid date", "artist": {"name": "Name"}}'
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': url,
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }

    router = PathRouter()
    router.post(url)(endpoint)

    app = WsgiApp(router)
    app.config.binder = binder
    app.config.json_serializer = json_serializer

    returned_status = None

    def start_response(status, headers):
        nonlocal returned_status
        returned_status = status

    response = b''.join(app(env, start_response))
    # XXX python 3.13 uses second variant
    assert returned_status in ('422 Unprocessable Entity', '422 Unprocessable Content')
    assert response == b'{"_errors": [{"loc": ["release_date"], "type": "date_from_datetime_parsing"}]}'
