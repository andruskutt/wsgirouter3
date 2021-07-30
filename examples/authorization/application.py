"""Authorization check example for wsgirouter3."""

from http import HTTPStatus
from wsgiref.simple_server import make_server

from wsgirouter3 import HTTPError, PathRouter, Request, WsgiApp


router = PathRouter()
_PUBLIC_ROUTE = {'authorization': False}


# assume by default routes are secured (no options given to route)
@router.route('/get', methods=('GET',))
def secured_handler(request: Request) -> dict:
    # dict is converted to json
    return request.environ


# public route as exception (options with flag)
@router.route('/public/get', methods=('GET',), options=_PUBLIC_ROUTE)
def public_handler(request: Request) -> dict:
    # remove values not supported by default json serialization
    result = {**request.environ}
    result.pop('wsgi.file_wrapper', None)
    result.pop('wsgi.input', None)
    result.pop('wsgi.errors', None)
    return result


def check_authorization(request: Request) -> None:
    options = request.environ[router.options_key]
    if not (isinstance(options, dict) and options.get('authorization') is False):
        # TODO: check for authorization
        raise HTTPError(HTTPStatus.UNAUTHORIZED, headers={'WWW-Authenticate': 'Bearer'})


# WSGI application using default config
app = WsgiApp(router)
app.config.before_request = check_authorization
port = 8000

with make_server('', port, app) as httpd:
    print(f'Serving HTTP on port {port}...')

    # Respond to requests until process is killed
    httpd.serve_forever()
