import requests
from flask import current_app
from requests.exceptions import HTTPError

def api_get(endpoint: str, params: dict = None):
    base_url = current_app.config["INTEGRATIONS_BASE_URL"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    token = f"Bearer {current_app.config['INTEGRATIONS_TOKEN']}"
    headers = {
        "Authorization": token
    }

    response = requests.get(url, headers=headers, params=params, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Get Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()

def api_post(endpoint: str, payload: dict = None, params: dict = None):
    base_url = current_app.config["INTEGRATIONS_BASE_URL"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    token = f"Bearer {current_app.config['INTEGRATIONS_TOKEN']}"
    headers = {
        "Authorization": token
    }
    response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Post Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()

def api_put(endpoint: str, payload: dict = None, params: dict = None):
    base_url = current_app.config["INTEGRATIONS_BASE_URL"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    token = f"Bearer {current_app.config['INTEGRATIONS_TOKEN']}"
    headers = {
        "Authorization": token
    }
    response = requests.put(url, headers=headers, params=params, json=payload, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Put Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()

def api_delete(endpoint: str, payload: dict = None, params: dict = None):
    base_url = current_app.config["INTEGRATIONS_BASE_URL"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    token = f"Bearer {current_app.config['INTEGRATIONS_TOKEN']}"
    headers = {
        "Authorization": token
    }
    response = requests.delete(url, headers=headers, json=payload, params=params, timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as e:
        current_app.logger.error(f"API Delete Failed: {e.response.status_code} - {e.response.text}")
        raise
    return response.json()