"""Tests for WSGI functionality using orjson json serializer/deserializer."""

import io
from http import HTTPStatus

import orjson

from wsgirouter3 import Request, WsgiAppConfig


def test_request_json_orjson():
    json_bytes = b'{"A": 1, "B": true, "C": null, "D": 0.1}'
    env = {
        'CONTENT_TYPE': 'application/json',
        'wsgi.input': io.BytesIO(json_bytes),
        'CONTENT_LENGTH': f'{len(json_bytes)}',
    }
    config = WsgiAppConfig()
    config.json_deserializer = orjson.loads
    r = Request(config, env)
    assert r.json == {'A': 1, 'B': True, 'C': None, 'D': 0.1}


def test_response_conversion_dict_orjson():
    conf = WsgiAppConfig()
    conf.json_serializer = orjson.dumps
    env = {'REQUEST_METHOD': 'GET'}

    json_response = (HTTPStatus.OK, (b'{"B":"blaah"}',), {'Content-Type': 'application/json', 'Content-Length': '13'})
    assert conf.result_handler(env, {'B': 'blaah'}) == json_response
