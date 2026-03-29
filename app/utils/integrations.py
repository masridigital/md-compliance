import requests
from flask import current_app
from requests.exceptions import HTTPError, RequestException


class IntegrationsNotConfiguredError(Exception):
    """Raised when the integrations platform is not configured."""
    pass


def _get_base_url_and_headers():
    """Return (base_url, headers) or raise IntegrationsNotConfiguredError."""
    base_url = current_app.config.get("INTEGRATIONS_BASE_URL")
    token = current_app.config.get("INTEGRATIONS_TOKEN")
    if not base_url or not token:
        raise IntegrationsNotConfiguredError(
            "Integrations platform is not configured. "
            "Set INTEGRATIONS_BASE_URL and INTEGRATIONS_TOKEN in your environment."
        )
    return base_url, {"Authorization": f"Bearer {token}"}


def api_get(endpoint: str, params: dict = None):
    base_url, headers = _get_base_url_and_headers()
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Get Failed: {e.response.status_code} - {e.response.text}")
        raise
    except RequestException as e:
        current_app.logger.error(f"API Get network error: {e}")
        raise
    return response.json()

def api_post(endpoint: str, payload: dict = None, params: dict = None):
    base_url, headers = _get_base_url_and_headers()
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Post Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()

def api_put(endpoint: str, payload: dict = None, params: dict = None):
    base_url, headers = _get_base_url_and_headers()
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    response = requests.put(url, headers=headers, params=params, json=payload, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Put Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()

def api_delete(endpoint: str, payload: dict = None, params: dict = None):
    base_url, headers = _get_base_url_and_headers()
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    response = requests.delete(url, headers=headers, json=payload, params=params, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Delete Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()
