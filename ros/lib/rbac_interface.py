from urllib.parse import urljoin
from http import HTTPStatus
from flask_restful import abort
from .config import RBAC_SVC_URL, ENABLE_RBAC, TLS_CA_PATH
import requests


RBAC_SVC_ENDPOINT = "/api/rbac/v1/access/?application=%s"
AUTH_HEADER_NAME = "X-RH-IDENTITY"
VALID_HTTP_VERBS = ["get", "options", "head", "post", "put", "patch", "delete"]


def fetch_url(url, auth_header, logger, method="get"):
    """
    Helper to make a single request.
    """
    if method not in VALID_HTTP_VERBS:
        abort(
            HTTPStatus.METHOD_NOT_ALLOWED, message="'%s' is not valid HTTP method." % method
        )
    response = requests.request(
        method, url, headers=auth_header, verify=TLS_CA_PATH)
    _validate_service_response(response, logger, auth_header)
    return response.json()


def _validate_service_response(response, logger, auth_header):
    """
    Raise an exception if the response was not what we expected.
    """
    if response.status_code in [requests.codes.forbidden, requests.codes.unauthorized]:
        logger.info(
            f"{response.status_code} error received from service"
        )
        # Log identity header if 401 (unauthorized)
        if response.status_code == requests.codes.unauthorized:
            if isinstance(auth_header, dict) and AUTH_HEADER_NAME in auth_header:
                logger.info(f"Identity {get_key_from_headers(auth_header)}")
            else:
                logger.info("No identity or no key")
        abort(
            response.status_code, message="Unable to retrieve permissions."
        )
    else:
        if response.status_code == requests.codes.not_found:
            logger.error(f"{response.status_code} error received from service.")
            abort(
                response.status_code, message="The requested URL was not found."
            )
        if response.status_code != requests.codes.ok:
            logger.error(f"{response.status_code} error received from service.")
            abort(
                response.status_code, message="Error received from backend service"
            )


def get_key_from_headers(incoming_headers):
    """
    return auth key from header
    """
    return incoming_headers.get(AUTH_HEADER_NAME)


def get_perms(application, auth_key, logger):
    """
    check if user has a permission
    """

    auth_header = {AUTH_HEADER_NAME: auth_key}

    rbac_location = urljoin(RBAC_SVC_URL, RBAC_SVC_ENDPOINT) % application

    rbac_result = fetch_url(
        rbac_location, auth_header, logger)
    perms = [perm["permission"] for perm in rbac_result["data"]]

    return perms


def ensure_has_permission(**kwargs):
    """
    Ensure permission exists. kwargs needs to contain:
    permissions, application, app_name, request, logger
    """

    request = kwargs["request"]
    auth_key = request.headers.get('X-RH-IDENTITY')

    if not ENABLE_RBAC:
        return

    if _is_mgmt_url(request.path):
        return  # allow request
    if auth_key:
        perms = get_perms(
            kwargs["application"],
            auth_key,
            kwargs["logger"]
        )
        if perms:
            for p in perms:
                if p in kwargs["permissions"]:
                    return  # allow
        # if wrong permissions
        abort(
            HTTPStatus.FORBIDDEN,
            message='User does not have correct permissions to access the service'
        )
    else:
        # if no auth_key
        abort(
            HTTPStatus.BAD_REQUEST, message="Identity not found in request"
        )


def _is_mgmt_url(path):
    """
    Small helper to test if URL is for management API.
    """
    return path.startswith("/mgmt/")
