## 0.8.4 (2023-01-07)

### Features

* allow deserializing of application/json subtypes: application/some-subtype+json

## 0.8.3 (2022-11-28)

### Features

* fixed direct mapping path for subrouter root entry

## 0.8.2 (2022-11-20)

### Features

* removed multipart/form-data support as cgi module is deprecated. Use external library for this
* do not cache Request.form, Request.json, Request.method and Request.query_parameters properties
* IntPathParameter matches value using isdecimal()

## 0.8.1 (2022-08-03)

### Features

* Cache-Control public directive support for responses
* pypy3 supported

## 0.8.0 (2022-07-22)

### Features

* Cache-Control header support for responses

## 0.7.2 (2022-07-03)

### Features

* ETag handling (strong -> weak) for compressed responses
* changed typing info for readonly dicts to Mapping

## 0.7.1 (2022-06-25)

### Features

* defaults for handler parameters are type-checked
* defaults are only allowed for handler parameters which do not get values from path/query string/body
* handler parameter types can wrapped with Annotated

## 0.7.0 (2022-06-16)

### Features

* removed WsgiAppConfig.logger configuration. Override error_handler to change unhandled exception logging behaviour
* removed WsgiAppConfig.json_result_handler configuration

### Refactoring

* do not concatenate compressed result parts

## 0.6.1 (2022-03-26)

### Features

* added more typing info
* binding tests/examples using marshmallow and pydantic

## 0.6.0 (2021-12-22)

### Features

* configurable compression level. Lowered default level from 6 to 2.
* route paths must always start with /
* made route options again accessible in before_request hook (broken in 0.3.0)

### Refactoring

* pass dataclass object to json serializer, do not convert it to dict too early. Possible performance gain with serializers which support native dataclass serialization.

## 0.5.0 (2021-12-14)

### Features

* added compression support for responses. By default enabled for application/json
* Accept header negotiation now uses quality value too (type with q=0 is ignored)
* fixed handling of Body and Query annotated parameters when PEP-563 is enabled

### Refactoring

* renamed configuration parameter max_content_length to max_request_content_length

## 0.4.0 (2021-12-02)

### Features

* shortcut route decorators for HTTP methods DELETE, GET, PATCH, POST, PUT

## 0.3.0 (2021-10-31)

### Features

* multiple mime types supported in consumes parameter when defining route

### Refactoring

* Query and Body binding markers are now Annotated aliases. For python < 3.9 this requires external dependency typing_extensions.
* removed knowledge about request handling details inside PathRouter
* PathRouter returns routes using generator

## 0.2.0 (2021-10-09)

### Features

* do not store route_path used for endpoint handler registration
* added direct route_path, endpoint mapping for handlers without path parameters
* support Request subclasses as type hints for handler wsgi environ wrapper parameter
* python 3.10 supported

## 0.1.0 (2021-10-02)

* initial release
