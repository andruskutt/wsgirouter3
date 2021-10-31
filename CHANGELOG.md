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
