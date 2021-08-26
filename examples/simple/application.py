"""Examples for wsgirouter3."""

from http import HTTPStatus
from typing import Optional
from wsgiref.simple_server import make_server

from wsgirouter3 import PathRouter, Query, Request, WsgiApp


router = PathRouter()


# handler gets query string as parameter if there is parameter with generic type Query
# adding route with decorator
@router.route('/get', methods=('GET',))
def get(query: Query[dict]) -> dict:
    # dict is converted to json
    return {'query_parameters': query}


# parameter type is taken from handler method signature
@router.route('/post/{some_id}', methods=('POST',))
def post_with_id(some_id: int) -> tuple:
    # status-only result as single element tuple
    return HTTPStatus.NO_CONTENT,


# multiple routes for same endpoint
@router.route('/put', methods=('PUT',), defaults={'some_id': None})
@router.route('/put/{some_id}', methods=('PUT',))
def put_with_id(some_id: Optional[int]) -> tuple:
    return HTTPStatus.NO_CONTENT,


# handler gets wsgi environ wrapper as parameter if there is parameter with type Request
# to get HEAD method support, just list it in methods
@router.route('/get_or_head', methods=('GET', 'HEAD'))
def get_or_head(request: Request) -> dict:
    # remove values not supported by default json serialization
    result = {**request.environ}
    result.pop('wsgi.file_wrapper', None)
    result.pop('wsgi.input', None)
    result.pop('wsgi.errors', None)
    return result


def handler() -> tuple:
    # status, result and headers
    # Content-Type=text/plain is added by default for str result
    return (HTTPStatus.OK, 'OK', {'X-Custom-Header': 'Value'})


# adding route without decorator
router.add_route('/handler', methods=('GET',), handler=handler)

# WSGI application using default config
app = WsgiApp(router)
port = 8000

with make_server('', port, app) as httpd:
    print(f'Serving HTTP on port {port}...')

    # Respond to requests until process is killed
    httpd.serve_forever()
