"""Examples for wsgirouter3."""

from http import HTTPStatus
from typing import Optional
from wsgiref.simple_server import make_server

from wsgirouter3 import PathRouter, Request, WsgiApp


router = PathRouter()


# adding route with decorator
@router.route('/get', methods=('GET',))
def get(request: Request) -> dict:
    # dict is converted to json
    return {'query_parameters': request.query_parameters}


# parameter type is taken from handler method signature
@router.route('/post/{id}', methods=('POST',))
def post_with_id(request: Request, id: int) -> tuple:
    # status-only result as single element tuple
    return HTTPStatus.NO_CONTENT,


# multiple routes for same endpoint
@router.route('/put', methods=('PUT',), defaults={'id': None})
@router.route('/put/{id}', methods=('PUT',))
def put_with_id(request: Request, id: Optional[int]) -> dict:
    return HTTPStatus.NO_CONTENT,


# to get HEAD method support, just list it in methods
@router.route('/get_or_head', methods=('GET', 'HEAD'))
def get_or_head(request: Request) -> dict:
    return request.environ


# handler gets wsgi environ wrapper as first parameter
def handler(request: Request) -> tuple:
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
