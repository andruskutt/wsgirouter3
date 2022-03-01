"""Tests for parameter binding using marshmallow."""

import io
import json
from http import HTTPStatus

from marshmallow import Schema, ValidationError, fields

from wsgirouter3 import Body, HTTPError, PathRouter, WsgiApp


class ArtistSchema(Schema):
    name = fields.Str()


class AlbumSchema(Schema):
    title = fields.Str()
    release_date = fields.Date()
    artist = fields.Nested(ArtistSchema())


def binder(data, schema):
    if not isinstance(data, dict):
        raise HTTPError(HTTPStatus.BAD_REQUEST)

    # XXX https://github.com/marshmallow-code/marshmallow/issues/783
    instance = schema()
    try:
        return instance.load(data)
    except ValidationError as e:
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, e.messages)


def json_serializer(data):
    return json.dumps(data, default=str).encode()


def start_response(status, headers):
    pass


def endpoint(body: Body[AlbumSchema]) -> dict:
    # body is of type dict
    return body


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
    assert returned_status == '422 Unprocessable Entity'
    assert response == b'{"release_date": ["Not a valid date."]}'
