"""
Masri Digital Compliance Platform — Storage Providers

Abstract base + concrete implementations for multi-provider file storage.
Extends the existing gapps FileStorageHandler pattern with an ABC interface
and adds Azure Blob, SharePoint, and Egnyte support.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO
import os
import time
import shutil
import logging
import json

logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """Abstract interface for all storage backends."""

    @abstractmethod
    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        """Upload a file. Returns the stored path/URL."""

    @abstractmethod
    def get_file(self, path: str) -> bytes:
        """Download file contents as bytes."""

    @abstractmethod
    def delete_file(self, path: str) -> bool:
        """Delete a file. Returns True on success."""

    @abstractmethod
    def list_files(self, folder: str) -> list:
        """List files in a folder. Returns list of dicts with name, path, size."""

    @abstractmethod
    def test_connection(self) -> dict:
        """
        Test connectivity to this storage backend.
        Returns: {success: bool, message: str, latency_ms: int}
        """


# ===========================================================================
# Local Storage
# ===========================================================================

class LocalStorageProvider(StorageProvider):
    """Local filesystem storage with path traversal protection."""

    def __init__(self, base_path: str):
        self.base_path = os.path.realpath(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    def _safe_path(self, *parts):
        """Resolve path and ensure it stays within base_path. Prevents traversal."""
        joined = os.path.join(self.base_path, *parts)
        resolved = os.path.realpath(joined)
        if not resolved.startswith(self.base_path):
            raise PermissionError(f"Path traversal blocked: {resolved}")
        return resolved

    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(file_name) or "unnamed_file"
        dest_dir = self._safe_path(folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, safe_name)
        # Final check after joining filename
        if not os.path.realpath(dest_path).startswith(self.base_path):
            raise PermissionError("Path traversal blocked in filename")

        if isinstance(file, str):
            shutil.move(file, dest_path)
        elif hasattr(file, "save"):
            file.save(dest_path)
        else:
            with open(dest_path, "wb") as f:
                f.write(file.read())

        return dest_path

    def get_file(self, path: str) -> bytes:
        full_path = self._safe_path(path) if not os.path.isabs(path) else path
        # Always validate against base_path even for absolute paths
        if not os.path.realpath(full_path).startswith(self.base_path):
            raise PermissionError("Path traversal blocked")
        if not os.path.isfile(full_path):
            raise FileNotFoundError("File not found")
        with open(full_path, "rb") as f:
            return f.read()

    def delete_file(self, path: str) -> bool:
        full_path = self._safe_path(path) if not os.path.isabs(path) else path
        if not os.path.realpath(full_path).startswith(self.base_path):
            raise PermissionError("Path traversal blocked")
        if not os.path.isfile(full_path):
            raise FileNotFoundError("File not found")
        os.remove(full_path)
        return True

    def list_files(self, folder: str) -> list:
        full_path = self._safe_path(folder)
        if not os.path.isdir(full_path):
            return []
        results = []
        for name in os.listdir(full_path):
            fpath = os.path.join(full_path, name)
            if os.path.isfile(fpath):
                results.append({
                    "name": name,
                    "path": os.path.join(folder, name),
                    "size": os.path.getsize(fpath),
                })
        return results

    def test_connection(self) -> dict:
        start = time.time()
        try:
            os.makedirs(self.base_path, exist_ok=True)
            test_file = os.path.join(self.base_path, ".connection_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            latency = int((time.time() - start) * 1000)
            return {"success": True, "message": "Local storage accessible", "latency_ms": latency}
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"success": False, "message": str(e), "latency_ms": latency}


# ===========================================================================
# AWS S3 / S3-Compatible (MinIO, Cloudflare R2)
# ===========================================================================

class S3StorageProvider(StorageProvider):
    """AWS S3 or S3-compatible storage (MinIO, Cloudflare R2). Uses boto3."""

    def __init__(self, bucket: str, region: str = None, access_key: str = None,
                 secret_key: str = None, endpoint_url: str = None):
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 storage. Install it with: "
                "pip install boto3"
            )
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.ClientError = ClientError

        kwargs = {}
        if region:
            kwargs["region_name"] = region
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        self.client = boto3.client("s3", **kwargs)

    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        key = f"{folder}/{file_name}".lstrip("/")
        if hasattr(file, "read"):
            self.client.upload_fileobj(file, self.bucket, key)
        else:
            self.client.upload_file(str(file), self.bucket, key)
        return key

    def get_file(self, path: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=path)
        return obj["Body"].read()

    def delete_file(self, path: str) -> bool:
        self.client.delete_object(Bucket=self.bucket, Key=path)
        return True

    def list_files(self, folder: str) -> list:
        prefix = folder.rstrip("/") + "/" if folder else ""
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        results = []
        for obj in response.get("Contents", []):
            results.append({
                "name": os.path.basename(obj["Key"]),
                "path": obj["Key"],
                "size": obj["Size"],
            })
        return results

    def test_connection(self) -> dict:
        start = time.time()
        try:
            self.client.head_bucket(Bucket=self.bucket)
            latency = int((time.time() - start) * 1000)
            return {"success": True, "message": f"Connected to S3 bucket: {self.bucket}", "latency_ms": latency}
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"success": False, "message": str(e), "latency_ms": latency}


# ===========================================================================
# Azure Blob Storage
# ===========================================================================

class AzureBlobStorageProvider(StorageProvider):
    """
    Azure Blob Storage. Supports account key auth + managed identity.
    Per-tenant container mode: container name = f'tenant-{tenant_id}'
    """

    def __init__(self, account_name: str, account_key: str = None,
                 use_managed_identity: bool = False,
                 container: str = "compliance-evidence",
                 per_tenant_containers: bool = False,
                 tenant_id: str = None):
        try:
            from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        except ImportError:
            raise ImportError(
                "azure-storage-blob is required. Install with: "
                "pip install azure-storage-blob azure-identity"
            )
        self.account_name = account_name
        self.per_tenant_containers = per_tenant_containers
        self.tenant_id = tenant_id
        self._generate_blob_sas = generate_blob_sas
        self._BlobSasPermissions = BlobSasPermissions
        self._account_key = account_key

        if per_tenant_containers and tenant_id:
            self.container = f"tenant-{tenant_id}"
        else:
            self.container = container

        account_url = f"https://{account_name}.blob.core.windows.net"

        if use_managed_identity:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            self.service_client = BlobServiceClient(
                account_url=account_url, credential=credential
            )
        elif account_key:
            self.service_client = BlobServiceClient(
                account_url=account_url, credential=account_key
            )
        else:
            raise ValueError("Either account_key or use_managed_identity must be set")

        self.container_client = self.service_client.get_container_client(self.container)

    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        blob_name = f"{folder}/{file_name}".lstrip("/")
        blob_client = self.container_client.get_blob_client(blob_name)
        if hasattr(file, "read"):
            blob_client.upload_blob(file, overwrite=True)
        else:
            with open(str(file), "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
        return blob_name

    def get_file(self, path: str) -> bytes:
        blob_client = self.container_client.get_blob_client(path)
        return blob_client.download_blob().readall()

    def delete_file(self, path: str) -> bool:
        blob_client = self.container_client.get_blob_client(path)
        blob_client.delete_blob()
        return True

    def list_files(self, folder: str) -> list:
        prefix = folder.rstrip("/") + "/" if folder else ""
        results = []
        for blob in self.container_client.list_blobs(name_starts_with=prefix):
            results.append({
                "name": blob.name.split("/")[-1],
                "path": blob.name,
                "size": blob.size,
            })
        return results

    def test_connection(self) -> dict:
        start = time.time()
        try:
            self.container_client.get_container_properties()
            latency = int((time.time() - start) * 1000)
            return {
                "success": True,
                "message": f"Connected to Azure container: {self.container}",
                "latency_ms": latency,
            }
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"success": False, "message": str(e), "latency_ms": latency}

    def generate_sas_url(self, blob_path: str, expiry_hours: int = 24) -> str:
        """Generate a time-limited SAS URL for direct client access."""
        from datetime import datetime, timedelta, timezone
        sas_token = self._generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container,
            blob_name=blob_path,
            account_key=self._account_key,
            permission=self._BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )
        return (
            f"https://{self.account_name}.blob.core.windows.net/"
            f"{self.container}/{blob_path}?{sas_token}"
        )


# ===========================================================================
# SharePoint via Microsoft Graph API
# ===========================================================================

class SharePointStorageProvider(StorageProvider):
    """
    Microsoft SharePoint via Graph API. No heavy SDK — pure requests.
    Auto-creates folder structure: {library}/{framework_name}/{control_ref_code}/
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 site_url: str, document_library: str = "Compliance Evidence"):
        try:
            import requests as _requests
        except ImportError:
            raise ImportError("requests is required for SharePoint. pip install requests")

        self._requests = _requests
        self.ms_tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.site_url = site_url
        self.document_library = document_library
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self) -> str:
        """OAuth2 client credentials flow to graph.microsoft.com."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        url = f"https://login.microsoftonline.com/{self.ms_tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        resp = self._requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()
        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
        return self._access_token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    def _get_site_id(self) -> str:
        """Resolve SharePoint site URL to a Graph site ID."""
        from urllib.parse import urlparse
        parsed = urlparse(self.site_url)
        hostname = parsed.hostname
        site_path = parsed.path.rstrip("/")

        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
        resp = self._requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()["id"]

    def _get_drive_id(self, site_id: str) -> str:
        """Get drive ID for the document library."""
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        resp = self._requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        for drive in resp.json().get("value", []):
            if drive["name"] == self.document_library:
                return drive["id"]
        raise ValueError(f"Document library '{self.document_library}' not found")

    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        site_id = self._get_site_id()
        drive_id = self._get_drive_id(site_id)
        path = f"{folder}/{file_name}".replace("//", "/").strip("/")
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            f"/root:/{path}:/content"
        )
        content = file.read() if hasattr(file, "read") else open(str(file), "rb").read()
        headers = self._headers()
        headers["Content-Type"] = "application/octet-stream"
        resp = self._requests.put(url, headers=headers, data=content, timeout=120)
        resp.raise_for_status()
        return resp.json().get("webUrl", path)

    def get_file(self, path: str) -> bytes:
        site_id = self._get_site_id()
        drive_id = self._get_drive_id(site_id)
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            f"/root:/{path}:/content"
        )
        resp = self._requests.get(url, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        return resp.content

    def delete_file(self, path: str) -> bool:
        site_id = self._get_site_id()
        drive_id = self._get_drive_id(site_id)
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            f"/root:/{path}"
        )
        resp = self._requests.delete(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return True

    def list_files(self, folder: str) -> list:
        site_id = self._get_site_id()
        drive_id = self._get_drive_id(site_id)
        folder = folder.strip("/")
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            f"/root:/{folder}:/children"
        )
        resp = self._requests.get(url, headers=self._headers(), timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        results = []
        for item in resp.json().get("value", []):
            if "file" in item:
                results.append({
                    "name": item["name"],
                    "path": f"{folder}/{item['name']}",
                    "size": item.get("size", 0),
                    "web_url": item.get("webUrl"),
                })
        return results

    def list_folder(self, path: str) -> list:
        """Browse SharePoint folder for document picker UI."""
        return self.list_files(path)

    def get_item_by_url(self, sharepoint_url: str) -> dict:
        """Fetch file metadata from a SharePoint item URL."""
        from urllib.parse import quote
        encoded_url = quote(sharepoint_url, safe="")
        url = f"https://graph.microsoft.com/v1.0/shares/u!{encoded_url}/driveItem"
        resp = self._requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def test_connection(self) -> dict:
        start = time.time()
        try:
            site_id = self._get_site_id()
            self._get_drive_id(site_id)
            latency = int((time.time() - start) * 1000)
            return {
                "success": True,
                "message": f"Connected to SharePoint: {self.document_library}",
                "latency_ms": latency,
            }
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"success": False, "message": str(e), "latency_ms": latency}


# ===========================================================================
# Egnyte
# ===========================================================================

class EgnyteStorageProvider(StorageProvider):
    """Egnyte Public API. Token-based auth."""

    def __init__(self, domain: str, api_token: str,
                 root_folder: str = "/Shared/Compliance"):
        try:
            import requests as _requests
        except ImportError:
            raise ImportError("requests is required. pip install requests")

        self._requests = _requests
        self.domain = domain.rstrip("/")
        self.api_token = api_token
        self.root_folder = root_folder.rstrip("/")
        self.base_url = f"https://{self.domain}.egnyte.com/pubapi/v1"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_token}"}

    def _full_path(self, path: str) -> str:
        return f"{self.root_folder}/{path}".replace("//", "/")

    def upload_file(self, file: BinaryIO, file_name: str, folder: str) -> str:
        path = self._full_path(f"{folder}/{file_name}")
        url = f"{self.base_url}/fs-content{path}"
        content = file.read() if hasattr(file, "read") else open(str(file), "rb").read()
        headers = self._headers()
        headers["Content-Type"] = "application/octet-stream"
        resp = self._requests.post(url, headers=headers, data=content, timeout=120)
        resp.raise_for_status()
        return path

    def get_file(self, path: str) -> bytes:
        full = self._full_path(path)
        url = f"{self.base_url}/fs-content{full}"
        resp = self._requests.get(url, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        return resp.content

    def delete_file(self, path: str) -> bool:
        full = self._full_path(path)
        url = f"{self.base_url}/fs{full}"
        resp = self._requests.delete(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return True

    def list_files(self, folder: str) -> list:
        full = self._full_path(folder)
        url = f"{self.base_url}/fs{full}"
        resp = self._requests.get(url, headers=self._headers(), timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("files", []):
            results.append({
                "name": item["name"],
                "path": f"{folder}/{item['name']}",
                "size": item.get("size", 0),
            })
        return results

    def test_connection(self) -> dict:
        start = time.time()
        try:
            url = f"{self.base_url}/fs{self.root_folder}"
            resp = self._requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            latency = int((time.time() - start) * 1000)
            return {
                "success": True,
                "message": f"Connected to Egnyte: {self.domain}",
                "latency_ms": latency,
            }
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"success": False, "message": str(e), "latency_ms": latency}


# ===========================================================================
# Factory
# ===========================================================================

def get_storage_provider(provider_name: str, config: dict,
                         tenant_id: str = None) -> StorageProvider:
    """
    Factory function to instantiate a StorageProvider.

    Args:
        provider_name: local, s3, azure_blob, sharepoint, egnyte
        config: dict of provider-specific configuration
        tenant_id: optional, used for per-tenant container naming

    Returns:
        StorageProvider instance
    """
    provider_name = provider_name.lower()

    if provider_name == "local":
        return LocalStorageProvider(
            base_path=config.get("base_path", "/tmp/compliance-evidence")
        )
    elif provider_name == "s3":
        return S3StorageProvider(
            bucket=config["bucket"],
            region=config.get("region"),
            access_key=config.get("access_key"),
            secret_key=config.get("secret_key"),
            endpoint_url=config.get("endpoint_url"),
        )
    elif provider_name == "azure_blob":
        return AzureBlobStorageProvider(
            account_name=config["account_name"],
            account_key=config.get("account_key"),
            use_managed_identity=config.get("use_managed_identity", False),
            container=config.get("container", "compliance-evidence"),
            per_tenant_containers=config.get("per_tenant_containers", False),
            tenant_id=tenant_id,
        )
    elif provider_name == "sharepoint":
        return SharePointStorageProvider(
            tenant_id=config["ms_tenant_id"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            site_url=config["site_url"],
            document_library=config.get("document_library", "Compliance Evidence"),
        )
    elif provider_name == "egnyte":
        return EgnyteStorageProvider(
            domain=config["domain"],
            api_token=config["api_token"],
            root_folder=config.get("root_folder", "/Shared/Compliance"),
        )
    else:
        raise ValueError(
            f"Unknown storage provider: {provider_name}. "
            f"Supported: local, s3, azure_blob, sharepoint, egnyte"
        )
