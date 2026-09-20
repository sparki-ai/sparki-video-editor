#!/usr/bin/env python3
"""Dependency-free Sparki runner for browser and cloud agent environments."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import mimetypes
import os
import re
import secrets
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Tuple


RUNNER_VERSION = "1.0.0"
DEFAULT_API_BASE_URL = "https://agent-api.sparki.io"
ALLOWED_API_HOSTS = frozenset({"agent-api.sparki.io"})
ALLOWED_CHANNELS = frozenset({"claude", "codex"})
ALLOWED_EXTENSIONS = frozenset({".mp4", ".mov"})
ALLOWED_ASPECT_RATIOS = frozenset({"9:16", "1:1", "16:9"})
VALID_DURATION_RANGES = frozenset({"<30s", "30s~60s", "60s~90s", ">90s", "custom"})
MAX_UPLOAD_SIZE = 3 * 1024 * 1024 * 1024
MAX_FILES = 10
MAX_JSON_BYTES = 2 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MAX_DOWNLOAD_REDIRECTS = 5
AUTHORIZATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
API_KEY_PATTERN = re.compile(r"^sk_live_[A-Za-z0-9_-]{43}$")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")

STYLE_CATALOG: Dict[str, Dict[str, Any]] = {
    # Keep this small standalone catalog aligned with sparki-cli constants.
    "vlog/daily": {"tags": ["21"], "agent_type": "vlog_skill"},
    "vlog/travel": {
        "tags": ["64"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "travel",
    },
    "vlog/sports": {
        "tags": ["19"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "sports",
    },
    "vlog/chill-vibe": {"tags": ["23"], "agent_type": "vlog_skill"},
    "clips/long-to-short": {"tags": ["70"], "agent_type": "vlog_skill"},
    "clips/highlight-reel": {"tags": ["28"], "agent_type": "vlog_skill"},
    "narrative/podcast-interview": {
        "tags": ["33"],
        "agent_type": "vlog_skill",
    },
    "narrative/funny-commentary": {
        "tags": ["25"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "film_commentary",
    },
    "narrative/master-storyteller": {
        "tags": ["26"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "film_commentary",
    },
    "tools/ai-captions": {
        "tags": ["72"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "ai_caption",
        "default_prompt": "Add captions to the video.",
    },
    "tools/ai-translation": {
        "tags": ["73"],
        "agent_type": "vlog_skill",
        "vlog_skill_category": "ai_caption",
        "default_prompt": "Add Spanish captions to the video.",
    },
}

ERROR_ACTIONS = {
    "AUTH_FAILED": "Start a new browser authorization and approve access again.",
    "AUTHORIZATION_PENDING": "Open the authorization URL, sign in, approve access, then run the same command again.",
    "AUTHORIZATION_EXPIRED": "Run authorize again to create a new authorization URL.",
    "ACCESS_DENIED": "Run authorize again and approve access in the browser.",
    "QUOTA_EXCEEDED": "Top up or upgrade the Sparki account at https://sparki.io/.",
    "STORAGE_FULL": "Manage uploaded assets at https://sparki.io/, then retry.",
    "CONCURRENT_LIMIT": "Wait for a running Sparki project to complete, then retry.",
    "FILE_TOO_LARGE": "Compress or trim the video below the 3 GB upload limit.",
    "INVALID_FILE_FORMAT": "Use an MP4 or MOV video file.",
    "INVALID_STYLE": "Choose a style listed by this runner's --help output.",
    "INVALID_MODE": "Choose style-guided, prompt-driven, or style-clone.",
    "INVALID_REFERENCE": "Provide exactly one HTTPS reference URL or local reference file.",
    "NETWORK_ERROR": "Check whether this environment can reach agent-api.sparki.io, then retry.",
}


@dataclass
class RunnerError(Exception):
    """Represent a stable, secret-safe runner failure."""

    code: str
    message: str
    action: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return the public error message."""
        return self.message


@dataclass
class PreparedRun:
    """Contain validated inputs before browser credentials are exchanged."""

    files: List[Path]
    reference_file: Optional[Path]
    reference_url: Optional[str]
    output: Path
    project_body: Dict[str, Any]
    mode: str


class JsonArgumentParser(argparse.ArgumentParser):
    """Return command-line validation failures through the JSON error contract."""

    def error(self, message: str) -> NoReturn:
        """Raise a structured argument error instead of printing usage text."""
        raise RunnerError(
            "INVALID_ARGUMENT",
            message,
            "Run the command with --help and correct the arguments.",
        )


class HttpTransport:
    """Provide small HTTPS, JSON, upload, and download primitives."""

    def __init__(self, timeout: int = 30) -> None:
        """Initialize the transport.

        Args:
            timeout: Default socket timeout in seconds.
        """
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context()

    def _connection(
        self,
        url: str,
        *,
        timeout: Optional[int] = None,
    ) -> Tuple[http.client.HTTPSConnection, str]:
        """Build an HTTPS connection with standard proxy environment support.

        Args:
            url: Absolute HTTPS URL.
            timeout: Optional socket timeout override.

        Returns:
            A connection and origin-form request target.

        Raises:
            RunnerError: If the URL or configured proxy is unsafe.
        """
        parsed = _parse_https_url(url, code="NETWORK_ERROR")
        target_host = parsed.hostname or ""
        target_port = parsed.port or 443
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        proxy_url = urllib.request.getproxies().get("https")
        if proxy_url and not urllib.request.proxy_bypass(target_host):
            if "://" not in proxy_url:
                proxy_url = f"http://{proxy_url}"
            proxy = urllib.parse.urlsplit(proxy_url)
            if proxy.scheme.lower() != "http" or not proxy.hostname:
                raise RunnerError(
                    "NETWORK_ERROR",
                    "The configured HTTPS proxy is unsupported",
                    "Use a standard HTTP CONNECT proxy for HTTPS traffic.",
                )
            connection = http.client.HTTPSConnection(
                proxy.hostname,
                proxy.port or 80,
                timeout=timeout or self.timeout,
                context=self.ssl_context,
            )
            tunnel_headers: Dict[str, str] = {}
            if proxy.username is not None:
                password = proxy.password or ""
                credentials = f"{urllib.parse.unquote(proxy.username)}:{urllib.parse.unquote(password)}"
                encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
                tunnel_headers["Proxy-Authorization"] = f"Basic {encoded}"
            connection.set_tunnel(target_host, target_port, headers=tunnel_headers)
            return connection, path

        connection = http.client.HTTPSConnection(
            target_host,
            target_port,
            timeout=timeout or self.timeout,
            context=self.ssl_context,
        )
        return connection, path

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, Dict[str, str], Dict[str, Any]]:
        """Send one JSON request and parse a bounded object response.

        Args:
            method: HTTP method.
            url: Absolute HTTPS URL.
            payload: Optional JSON request body.
            headers: Optional request headers.
            timeout: Optional socket timeout override.

        Returns:
            HTTP status, normalized response headers, and JSON object.

        Raises:
            RunnerError: If transport or response parsing fails.
        """
        body = None
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"Sparki-Web-Runner/{RUNNER_VERSION}",
        }
        if headers:
            request_headers.update(headers)
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(body))

        connection, target = self._connection(url, timeout=timeout)
        try:
            connection.request(method, target, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = _read_bounded(response, MAX_JSON_BYTES)
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            if not raw:
                parsed: Any = {}
            else:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RunnerError(
                        "INVALID_RESPONSE",
                        "Sparki returned an invalid JSON response",
                        "Retry the request. If it persists, contact Sparki support.",
                    ) from exc
            if not isinstance(parsed, dict):
                raise RunnerError(
                    "INVALID_RESPONSE",
                    "Sparki returned an unexpected response shape",
                    "Retry the request. If it persists, contact Sparki support.",
                )
            return response.status, response_headers, parsed
        except RunnerError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise RunnerError(
                "NETWORK_ERROR",
                "Cannot reach Sparki servers",
                ERROR_ACTIONS["NETWORK_ERROR"],
                {"reason": type(exc).__name__},
            ) from exc
        finally:
            connection.close()

    def upload_file(
        self,
        url: str,
        file_path: Path,
        *,
        headers: Mapping[str, str],
        timeout: int,
    ) -> Tuple[int, Dict[str, Any]]:
        """Stream one file as multipart/form-data without buffering it.

        Args:
            url: Sparki upload endpoint.
            file_path: Validated local video file.
            headers: Authentication headers.
            timeout: Upload socket timeout in seconds.

        Returns:
            HTTP status and parsed JSON response.

        Raises:
            RunnerError: If upload or response parsing fails.
        """
        boundary = f"----SparkiWebRunner{secrets.token_hex(16)}"
        fallback_name = _ascii_multipart_filename(file_path)
        encoded_name = urllib.parse.quote(file_path.name, safe="")
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        preamble = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; "
            f"filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("ascii")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        content_length = len(preamble) + file_path.stat().st_size + len(suffix)
        request_headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(content_length),
            "User-Agent": f"Sparki-Web-Runner/{RUNNER_VERSION}",
            **headers,
        }
        connection, target = self._connection(url, timeout=timeout)
        try:
            connection.putrequest("POST", target)
            for name, value in request_headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.send(preamble)
            with file_path.open("rb") as source:
                while True:
                    chunk = source.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    connection.send(chunk)
            connection.send(suffix)
            response = connection.getresponse()
            raw = _read_bounded(response, MAX_JSON_BYTES)
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RunnerError(
                    "INVALID_RESPONSE",
                    "Sparki returned an invalid upload response",
                    "Retry the upload.",
                ) from exc
            if not isinstance(parsed, dict):
                raise RunnerError(
                    "INVALID_RESPONSE",
                    "Sparki returned an unexpected upload response",
                    "Retry the upload.",
                )
            return response.status, parsed
        except RunnerError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise RunnerError(
                "UPLOAD_FAILED",
                f"Upload failed for {file_path.name}",
                "Check the connection and retry the same run command.",
                {"reason": type(exc).__name__},
            ) from exc
        finally:
            connection.close()

    def download(self, url: str, output_path: Path, *, timeout: int) -> int:
        """Stream an HTTPS result into an atomic local output file.

        Args:
            url: Server-provided HTTPS result URL.
            output_path: Final local path.
            timeout: Download socket timeout in seconds.

        Returns:
            Number of bytes written.

        Raises:
            RunnerError: If redirects, transport, or filesystem writes fail.
        """
        current_url = _validate_result_url(url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None
        try:
            for redirect_count in range(MAX_DOWNLOAD_REDIRECTS + 1):
                connection, target = self._connection(current_url, timeout=timeout)
                try:
                    connection.request(
                        "GET",
                        target,
                        headers={"User-Agent": f"Sparki-Web-Runner/{RUNNER_VERSION}"},
                    )
                    response = connection.getresponse()
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.getheader("Location")
                        response.read(MAX_JSON_BYTES)
                        if not location:
                            raise RunnerError(
                                "DOWNLOAD_FAILED",
                                "The result download redirect has no destination",
                                "Retry the download later.",
                            )
                        if redirect_count >= MAX_DOWNLOAD_REDIRECTS:
                            raise RunnerError(
                                "DOWNLOAD_FAILED",
                                "The result download has too many redirects",
                                "Retry the download later.",
                            )
                        current_url = _validate_result_url(
                            urllib.parse.urljoin(current_url, location)
                        )
                        continue
                    if not 200 <= response.status < 300:
                        response.read(MAX_JSON_BYTES)
                        raise RunnerError(
                            "DOWNLOAD_FAILED",
                            f"Result download failed with HTTP {response.status}",
                            "Retry the download later.",
                        )
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        prefix=f".{output_path.name}.",
                        suffix=".part",
                        dir=str(output_path.parent),
                        delete=False,
                    ) as target_file:
                        temp_path = Path(target_file.name)
                        total = 0
                        while True:
                            chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            target_file.write(chunk)
                            total += len(chunk)
                        target_file.flush()
                        os.fsync(target_file.fileno())
                    os.replace(temp_path, output_path)
                    temp_path = None
                    return total
                finally:
                    connection.close()
            raise RunnerError(
                "DOWNLOAD_FAILED",
                "The result download could not be completed",
                "Retry the download later.",
            )
        except RunnerError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise RunnerError(
                "DOWNLOAD_FAILED",
                "Could not save the completed video",
                "Check the output directory and network connection, then retry.",
                {"reason": type(exc).__name__},
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _parse_https_url(url: str, *, code: str) -> urllib.parse.SplitResult:
    """Parse and validate one HTTPS URL.

    Args:
        url: URL to validate.
        code: Error code used for validation failures.

    Returns:
        Parsed URL.

    Raises:
        RunnerError: If the URL is not a safe absolute HTTPS URL.
    """
    if not isinstance(url, str) or CONTROL_CHARACTER_PATTERN.search(url):
        raise RunnerError(code, "Sparki returned an unsafe URL")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RunnerError(code, "Sparki returned an unsafe URL")
    return parsed


def _api_url(base_url: str, path: str) -> str:
    """Build an API URL after enforcing the production Sparki origin."""
    parsed = _parse_https_url(base_url, code="INVALID_API_ORIGIN")
    if parsed.hostname not in ALLOWED_API_HOSTS or parsed.port not in {None, 443}:
        raise RunnerError(
            "INVALID_API_ORIGIN",
            "The web runner only connects to agent-api.sparki.io",
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RunnerError("INVALID_API_ORIGIN", "The API base URL is invalid")
    return f"https://{parsed.hostname}{path}"


def _validate_result_url(url: str) -> str:
    """Validate a result URL received from an authenticated project response."""
    _parse_https_url(url, code="DOWNLOAD_FAILED")
    return url


def _validate_reference_url(url: str) -> str:
    """Validate a user-provided style reference URL."""
    _parse_https_url(url, code="INVALID_REFERENCE")
    return url


def _read_bounded(response: http.client.HTTPResponse, limit: int) -> bytes:
    """Read a response body while enforcing a memory limit."""
    body = response.read(limit + 1)
    if len(body) > limit:
        raise RunnerError(
            "INVALID_RESPONSE",
            "Sparki returned an unexpectedly large response",
        )
    return body


def _ascii_multipart_filename(file_path: Path) -> str:
    """Preserve safe ASCII names and provide a compatible Unicode fallback."""
    try:
        name = file_path.name.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        name = f"upload{file_path.suffix.lower()}"
    sanitized = re.sub(r"[\x00-\x1f\x7f\"\\]", "_", name)
    return sanitized or f"upload{file_path.suffix.lower()}"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """Parse and clamp one untrusted protocol timing value."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _error_action(code: str, fallback: str = "Retry the request.") -> str:
    """Return stable recovery guidance for one error code."""
    return ERROR_ACTIONS.get(code, fallback)


def _classify_api_error(
    http_status: int,
    envelope: Mapping[str, Any],
    *,
    default: str,
) -> RunnerError:
    """Convert a backend envelope into one safe public error."""
    data = envelope.get("data")
    safe_data = data if isinstance(data, dict) else {}
    explicit_code = safe_data.get("code")
    raw_envelope_code = envelope.get("code", http_status)
    try:
        envelope_code = int(raw_envelope_code)
    except (TypeError, ValueError):
        envelope_code = None
    if explicit_code is None:
        data_code = None
    else:
        try:
            data_code = int(explicit_code)
        except (TypeError, ValueError):
            data_code = None
    status_codes = {http_status, envelope_code, data_code}
    message = envelope.get("message")
    public_message = str(message) if isinstance(message, str) and message else "Sparki request failed"
    normalized = f"{explicit_code or ''} {raw_envelope_code or ''} {public_message}".lower()
    if isinstance(explicit_code, str) and not explicit_code.isdigit():
        code = str(explicit_code)
    elif isinstance(raw_envelope_code, str) and not raw_envelope_code.isdigit():
        code = raw_envelope_code
    elif (
        status_codes & {401, 403}
        or "api key" in normalized
        or "unauthorized" in normalized
    ):
        code = "AUTH_FAILED"
    elif 413 in status_codes and ("storage" in normalized or "quota" in normalized):
        code = "STORAGE_FULL"
    elif 413 in status_codes and ("file too large" in normalized or "too large" in normalized):
        code = "FILE_TOO_LARGE"
    elif 402 in status_codes or "credit" in normalized:
        code = "QUOTA_EXCEEDED"
    elif "storage" in normalized:
        code = "STORAGE_FULL"
    elif "quota" in normalized:
        code = "QUOTA_EXCEEDED"
    elif 429 in status_codes or "concurrent" in normalized:
        code = "CONCURRENT_LIMIT"
    else:
        code = default
    details = {
        key: safe_data[key]
        for key in ("interval", "retry_after")
        if key in safe_data
    }
    return RunnerError(code, public_message, _error_action(code), details)


def _unwrap_api_response(
    http_status: int,
    envelope: Mapping[str, Any],
    *,
    default_error: str,
) -> Dict[str, Any]:
    """Validate the shared Sparki API envelope and return its data object."""
    try:
        envelope_code = int(envelope.get("code", http_status))
    except (TypeError, ValueError):
        envelope_code = 500
    if not 200 <= http_status < 300 or not 200 <= envelope_code < 300:
        raise _classify_api_error(http_status, envelope, default=default_error)
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise RunnerError(
            "INVALID_RESPONSE",
            "Sparki returned an unexpected response shape",
        )
    return data


def _log(message: str) -> None:
    """Write progress to stderr so stdout remains machine-readable JSON."""
    print(message, file=sys.stderr, flush=True)


def _emit_success(data: Mapping[str, Any]) -> None:
    """Write one successful JSON result to stdout."""
    print(json.dumps({"ok": True, "data": data}, ensure_ascii=False, separators=(",", ":")))


def _emit_error(error: RunnerError) -> None:
    """Write one secret-safe JSON error to stdout."""
    payload: Dict[str, Any] = {
        "code": error.code,
        "message": error.message,
    }
    if error.action:
        payload["action"] = error.action
    if error.details:
        payload.update(error.details)
    print(json.dumps({"ok": False, "error": payload}, ensure_ascii=False, separators=(",", ":")))


def _pkce_pair() -> Tuple[str, str]:
    """Generate one S256 PKCE verifier and challenge."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _validate_verification_url(url: str, channel: str, authorization_id: str) -> str:
    """Require the exact production browser authorization URL shape."""
    parsed = _parse_https_url(url, code="INVALID_AUTHORIZATION_URL")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    expected_path = f"/connect/{channel}/start"
    if (
        parsed.hostname != "sparki.io"
        or parsed.port not in {None, 443}
        or parsed.path != expected_path
        or parsed.fragment
        or set(query) != {"authorization_id"}
        or query.get("authorization_id") != [authorization_id]
    ):
        raise RunnerError(
            "INVALID_AUTHORIZATION_URL",
            "Sparki returned an unexpected browser authorization URL",
        )
    return url


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    """Atomically write an authorization state file with private permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(state, target, separators=(",", ":"))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise


def _read_state(path: Path, *, allow_expired: bool = False) -> Dict[str, Any]:
    """Read and strictly validate one temporary browser authorization state."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerError(
            "AUTHORIZATION_REQUIRED",
            "No browser authorization state was found",
            "Run the authorize command first.",
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError(
            "STATE_INVALID",
            "The browser authorization state is unreadable",
            "Delete it with authorize --force and create a new authorization.",
        ) from exc
    if not isinstance(payload, dict):
        raise RunnerError("STATE_INVALID", "The browser authorization state is invalid")
    required = {
        "schema_version",
        "channel",
        "base_url",
        "authorization_id",
        "code_verifier",
        "verification_url",
        "expires_at",
        "interval",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise RunnerError("STATE_INVALID", "The browser authorization state is invalid")
    channel = payload.get("channel")
    authorization_id = payload.get("authorization_id")
    verifier = payload.get("code_verifier")
    if channel not in ALLOWED_CHANNELS:
        raise RunnerError("STATE_INVALID", "The browser authorization channel is invalid")
    if not isinstance(authorization_id, str) or not AUTHORIZATION_ID_PATTERN.fullmatch(authorization_id):
        raise RunnerError("STATE_INVALID", "The browser authorization identifier is invalid")
    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        raise RunnerError("STATE_INVALID", "The browser authorization verifier is invalid")
    _api_url(str(payload.get("base_url")), "/health")
    _validate_verification_url(
        str(payload.get("verification_url")),
        str(channel),
        authorization_id,
    )
    raw_expires_at = payload.get("expires_at")
    try:
        if not isinstance(raw_expires_at, (int, float, str)):
            raise TypeError
        expires_at = float(raw_expires_at)
    except (TypeError, ValueError) as exc:
        raise RunnerError("STATE_INVALID", "The browser authorization expiry is invalid") from exc
    if not allow_expired and expires_at <= time.time():
        raise RunnerError(
            "AUTHORIZATION_EXPIRED",
            "The browser authorization has expired",
            _error_action("AUTHORIZATION_EXPIRED"),
        )
    payload["interval"] = _bounded_int(payload.get("interval"), default=2, minimum=1, maximum=30)
    payload["expires_at"] = expires_at
    return payload


def _delete_state(path: Path) -> None:
    """Delete temporary authorization state without failing a completed exchange."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _log(f"Warning: could not remove temporary authorization state ({type(exc).__name__})")


def command_probe(args: argparse.Namespace, transport: HttpTransport) -> Dict[str, Any]:
    """Verify Python and production Sparki API connectivity."""
    url = _api_url(args.api_base_url, "/health")
    status, _headers, envelope = transport.request_json("GET", url)
    data = _unwrap_api_response(status, envelope, default_error="NETWORK_ERROR")
    return {
        "runner_version": RUNNER_VERSION,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "api_origin": DEFAULT_API_BASE_URL,
        "api_status": data.get("status", "reachable"),
    }


def command_authorize(args: argparse.Namespace, transport: HttpTransport) -> Dict[str, Any]:
    """Create or reuse one temporary browser authorization request."""
    state_path = args.state.expanduser().resolve()
    if state_path.exists() and not args.force:
        try:
            existing = _read_state(state_path)
        except RunnerError as error:
            if error.code != "AUTHORIZATION_EXPIRED":
                raise
            _delete_state(state_path)
        else:
            if existing["channel"] != args.channel:
                raise RunnerError(
                    "STATE_CHANNEL_MISMATCH",
                    "The existing authorization belongs to another channel",
                    "Use the matching channel or rerun authorize with --force.",
                )
            return {
                "authorization_url": existing["verification_url"],
                "channel": existing["channel"],
                "expires_at": existing["expires_at"],
                "state_path": str(state_path),
                "reused": True,
            }
    if args.force:
        _delete_state(state_path)

    verifier, challenge = _pkce_pair()
    url = _api_url(args.api_base_url, "/api/v1/cli-auth/request")
    status, _headers, envelope = transport.request_json(
        "POST",
        url,
        payload={
            "channel": args.channel,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    data = _unwrap_api_response(status, envelope, default_error="CLI_AUTH_UNAVAILABLE")
    authorization_id = data.get("authorization_id")
    if not isinstance(authorization_id, str) or not AUTHORIZATION_ID_PATTERN.fullmatch(authorization_id):
        raise RunnerError("INVALID_RESPONSE", "Sparki returned an invalid authorization identifier")
    verification_url = _validate_verification_url(
        str(data.get("verification_uri_complete", "")),
        args.channel,
        authorization_id,
    )
    expires_in = _bounded_int(data.get("expires_in"), default=600, minimum=30, maximum=1800)
    interval = _bounded_int(data.get("interval"), default=2, minimum=1, maximum=30)
    expires_at = time.time() + expires_in
    _write_state(
        state_path,
        {
            "schema_version": 1,
            "channel": args.channel,
            "base_url": args.api_base_url,
            "authorization_id": authorization_id,
            "code_verifier": verifier,
            "verification_url": verification_url,
            "expires_at": expires_at,
            "interval": interval,
        },
    )
    return {
        "authorization_url": verification_url,
        "channel": args.channel,
        "expires_at": expires_at,
        "state_path": str(state_path),
        "reused": False,
    }


def _exchange_authorization(
    state_path: Path,
    transport: HttpTransport,
) -> Tuple[str, Dict[str, Any]]:
    """Exchange an approved state for an in-memory API key."""
    state = _read_state(state_path)
    url = _api_url(state["base_url"], "/api/v1/cli-auth/token")
    try:
        status, _headers, envelope = transport.request_json(
            "POST",
            url,
            payload={
                "authorization_id": state["authorization_id"],
                "code_verifier": state["code_verifier"],
            },
        )
        data = _unwrap_api_response(status, envelope, default_error="CLI_AUTH_FAILED")
    except RunnerError as error:
        if error.code in {"AUTHORIZATION_PENDING", "SLOW_DOWN"}:
            delay = _bounded_int(
                error.details.get("retry_after", error.details.get("interval", state["interval"])),
                default=state["interval"],
                minimum=1,
                maximum=30,
            )
            raise RunnerError(
                error.code,
                error.message,
                _error_action("AUTHORIZATION_PENDING"),
                {
                    "authorization_url": state["verification_url"],
                    "retry_after": delay,
                    "state_path": str(state_path),
                },
            ) from error
        if error.code in {"ACCESS_DENIED", "AUTHORIZATION_EXPIRED"}:
            _delete_state(state_path)
        raise

    api_key = data.get("api_key")
    if not isinstance(api_key, str) or not API_KEY_PATTERN.fullmatch(api_key):
        raise RunnerError("INVALID_RESPONSE", "Sparki returned an invalid credential")
    if data.get("channel") != state["channel"]:
        raise RunnerError("INVALID_RESPONSE", "Sparki returned a credential for another channel")
    _delete_state(state_path)
    return api_key, state


def _validate_file(path: Path) -> Path:
    """Resolve and validate one local video path."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RunnerError("FILE_NOT_FOUND", f"Video file not found: {resolved}")
    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise RunnerError(
            "INVALID_FILE_FORMAT",
            f"Unsupported video format: {resolved.suffix or '(none)'}",
            _error_action("INVALID_FILE_FORMAT"),
        )
    size = resolved.stat().st_size
    if size <= 0:
        raise RunnerError("INVALID_FILE", f"Video file is empty: {resolved}")
    if size > MAX_UPLOAD_SIZE:
        raise RunnerError(
            "FILE_TOO_LARGE",
            f"Video exceeds the 3 GB limit: {resolved.name}",
            _error_action("FILE_TOO_LARGE"),
        )
    return resolved


def _validate_output(path: Path, protected_inputs: Sequence[Path] = ()) -> Path:
    """Resolve an MP4 output path and prevent destructive input overwrites."""
    output = path.expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        raise RunnerError("INVALID_OUTPUT", "The output path must end in .mp4")
    if output in set(protected_inputs):
        raise RunnerError(
            "INVALID_OUTPUT",
            "The output path must not overwrite a source or reference video",
        )
    if output.exists() and output.is_dir():
        raise RunnerError("INVALID_OUTPUT", "The output path points to a directory")
    return output


def _validate_task_id(value: str) -> str:
    """Normalize one backend project UUID for safe status requests."""
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise RunnerError("INVALID_TASK_ID", "The task_id must be a valid UUID") from exc


def _prepare_run(args: argparse.Namespace) -> PreparedRun:
    """Validate all run inputs before consuming browser authorization."""
    if not args.confirm_charge:
        raise RunnerError(
            "CONFIRMATION_REQUIRED",
            "Creating a Sparki editing project may consume credits",
            "Ask the user to approve the potentially paid task, then add --confirm-charge.",
        )
    if len(args.files) > MAX_FILES:
        raise RunnerError("TOO_MANY_FILES", f"At most {MAX_FILES} source videos are supported")
    files = list(dict.fromkeys(_validate_file(path) for path in args.files))
    reference_file = _validate_file(args.reference_file) if args.reference_file else None
    reference_url = _validate_reference_url(args.reference_url) if args.reference_url else None
    protected_inputs = set(files)
    if reference_file is not None:
        protected_inputs.add(reference_file)
    output = _validate_output(args.output, tuple(protected_inputs))
    reference_count = int(reference_file is not None) + int(reference_url is not None)

    if args.mode == "style-guided":
        if args.style not in STYLE_CATALOG:
            raise RunnerError("INVALID_STYLE", "Unknown or missing style", _error_action("INVALID_STYLE"))
        if reference_count:
            raise RunnerError("INVALID_MODE", "References are only valid in style-clone mode")
        style = STYLE_CATALOG[args.style]
        project_body: Dict[str, Any] = {
            "tags": style["tags"],
            "agent_type": style["agent_type"],
            "user_input": args.prompt or style.get("default_prompt", ""),
        }
        if style.get("vlog_skill_category"):
            project_body["vlog_skill_category"] = style["vlog_skill_category"]
    elif args.mode == "prompt-driven":
        if not args.prompt:
            raise RunnerError("INVALID_MODE", "Prompt-driven mode requires --prompt")
        if args.style or reference_count:
            raise RunnerError("INVALID_MODE", "Prompt-driven mode does not accept style or reference options")
        project_body = {
            "tags": ["71"],
            "agent_type": "vlog_skill",
            "user_input": args.prompt,
        }
    elif args.mode == "style-clone":
        if reference_count != 1:
            raise RunnerError(
                "INVALID_REFERENCE",
                "Style-clone mode requires exactly one reference",
                _error_action("INVALID_REFERENCE"),
            )
        if args.style or args.duration_range:
            raise RunnerError("INVALID_MODE", "Style-clone mode does not accept style or duration range")
        project_body = {"user_input": args.prompt or ""}
    else:
        raise RunnerError("INVALID_MODE", "Unknown edit mode", _error_action("INVALID_MODE"))

    if args.duration_range and args.duration_range not in VALID_DURATION_RANGES:
        raise RunnerError("INVALID_MODE", "Unknown duration range")
    project_body["generation_preferences"] = {"aspect_ratio": args.aspect_ratio}
    if args.duration_range:
        project_body["generation_preferences"]["duration_range"] = args.duration_range
    project_body["send_after_create"] = True
    return PreparedRun(
        files=files,
        reference_file=reference_file,
        reference_url=reference_url,
        output=output,
        project_body=project_body,
        mode=args.mode,
    )


def _authenticated_headers(api_key: str) -> Dict[str, str]:
    """Build API authentication headers without logging credentials."""
    return {"X-API-Key": api_key}


def _upload_and_wait(
    transport: HttpTransport,
    base_url: str,
    api_key: str,
    file_path: Path,
    *,
    upload_timeout: int,
    asset_timeout: int,
    asset_poll_interval: int,
) -> str:
    """Upload one video and wait for server-side asset processing."""
    _log(f"Uploading {file_path.name}...")
    status, envelope = transport.upload_file(
        _api_url(base_url, "/api/v1/assets/upload"),
        file_path,
        headers=_authenticated_headers(api_key),
        timeout=upload_timeout,
    )
    data = _unwrap_api_response(status, envelope, default_error="UPLOAD_FAILED")
    object_key = data.get("object_key") or data.get("objectKey")
    if not isinstance(object_key, str) or not object_key:
        raise RunnerError("INVALID_RESPONSE", "Sparki did not return an uploaded asset key")

    _log(f"Waiting for Sparki to process {file_path.name}...")
    deadline = time.monotonic() + asset_timeout
    while time.monotonic() < deadline:
        page = 1
        found: Optional[Mapping[str, Any]] = None
        while True:
            query = urllib.parse.urlencode({"page": page, "page_size": 50})
            try:
                response_status, _headers, response_envelope = transport.request_json(
                    "GET",
                    _api_url(base_url, f"/api/v1/assets/user_assets?{query}"),
                    headers=_authenticated_headers(api_key),
                )
                response_data = _unwrap_api_response(
                    response_status,
                    response_envelope,
                    default_error="UPLOAD_FAILED",
                )
            except RunnerError as error:
                if error.code == "NETWORK_ERROR":
                    _log("Asset status check failed; retrying...")
                    break
                raise
            items = response_data.get("assets", response_data.get("items", []))
            if not isinstance(items, list):
                raise RunnerError("INVALID_RESPONSE", "Sparki returned an invalid asset list")
            for item in items:
                if isinstance(item, dict) and (item.get("object_key") or item.get("objectKey")) == object_key:
                    found = item
                    break
            if found is not None or len(items) < 50:
                break
            page += 1
        if found is not None:
            asset_status = found.get("status")
            if asset_status == 1:
                return object_key
            if asset_status == -2:
                raise RunnerError("UPLOAD_FAILED", f"Asset processing failed for {file_path.name}")
        time.sleep(asset_poll_interval)
    raise RunnerError("RENDER_TIMEOUT", f"Asset processing timed out for {file_path.name}")


def _create_project(
    transport: HttpTransport,
    base_url: str,
    api_key: str,
    prepared: PreparedRun,
    object_keys: Sequence[str],
    reference_key: Optional[str],
) -> str:
    """Create exactly one editing project without automatic POST retries."""
    body = dict(prepared.project_body)
    if prepared.mode == "style-clone":
        reference: Dict[str, Any] = {"idx": 0, "media_type": "video"}
        if reference_key:
            reference["s3_object_key"] = reference_key
        else:
            reference["video_url"] = prepared.reference_url
        body["reference_resource"] = [reference]
        body["resources"] = [
            {"idx": index, "s3_object_key": key, "media_type": "video"}
            for index, key in enumerate(object_keys)
        ]
        path = "/api/v1/emulate/projects/"
    else:
        body["resources"] = [
            {"idx": index, "s3_object_key": key}
            for index, key in enumerate(object_keys)
        ]
        path = "/api/v1/projects/"
    _log("Creating one Sparki editing project...")
    status, _headers, envelope = transport.request_json(
        "POST",
        _api_url(base_url, path),
        payload=body,
        headers=_authenticated_headers(api_key),
    )
    data = _unwrap_api_response(status, envelope, default_error="PROJECT_CREATE_FAILED")
    task_id = data.get("task_id") or data.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise RunnerError("INVALID_RESPONSE", "Sparki did not return a project identifier")
    try:
        return _validate_task_id(task_id)
    except RunnerError as error:
        raise RunnerError(
            "INVALID_RESPONSE",
            "Sparki returned an invalid project identifier",
        ) from error


def _extract_result_url(data: Mapping[str, Any]) -> Optional[str]:
    """Extract the first result URL from compatible project response fields."""
    materials = data.get(
        "materials",
        data.get("outputResultAssets", data.get("output_result_assets", [])),
    )
    if not isinstance(materials, list) or not materials:
        return None
    item = materials[0]
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        result = item.get("url") or item.get("download_url") or item.get("downloadUrl")
        return result if isinstance(result, str) else None
    return None


def _wait_for_project(
    transport: HttpTransport,
    base_url: str,
    api_key: str,
    task_id: str,
    mode: str,
    *,
    timeout: int,
    poll_interval: int,
) -> Tuple[str, str]:
    """Poll one project until completion and return status and result URL."""
    if mode == "style-clone":
        path = f"/api/v1/emulate/projects/task/{urllib.parse.quote(task_id, safe='')}"
    else:
        path = f"/api/v1/projects/task/{urllib.parse.quote(task_id, safe='')}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _headers, envelope = transport.request_json(
                "GET",
                _api_url(base_url, path),
                headers=_authenticated_headers(api_key),
            )
            data = _unwrap_api_response(status, envelope, default_error="TASK_NOT_FOUND")
        except RunnerError as error:
            if error.code == "NETWORK_ERROR":
                _log("Project status check failed; retrying...")
                time.sleep(poll_interval)
                continue
            raise
        project_status = str(data.get("status", "")).upper()
        _log(f"Project {task_id} status: {project_status or 'UNKNOWN'}")
        if project_status == "COMPLETED":
            result_url = _extract_result_url(data)
            if not result_url:
                raise RunnerError("INVALID_RESPONSE", "Completed project has no result URL")
            return project_status, _validate_result_url(result_url)
        if project_status in {"FAILED", "CANCEL"}:
            raise RunnerError(
                "PROJECT_FAILED",
                f"Sparki project ended with status {project_status}",
                "Adjust the request or source video, then create a new project.",
                {"task_id": task_id},
            )
        time.sleep(poll_interval)
    raise RunnerError(
        "RENDER_TIMEOUT",
        "Sparki project processing timed out",
        "The project may still be running. Authorize again, then resume this task instead of creating a new project.",
        {"task_id": task_id, "mode": mode},
    )


def _add_project_recovery(
    error: RunnerError,
    *,
    task_id: str,
    mode: str,
    output: Path,
) -> RunnerError:
    """Attach safe resume data to a failure after project creation."""
    details = {
        **error.details,
        "task_id": task_id,
        "mode": mode,
        "output": str(output),
    }
    if error.code in {"RENDER_TIMEOUT", "DOWNLOAD_FAILED", "NETWORK_ERROR", "INVALID_RESPONSE"}:
        action = (
            "Do not run the full edit again. Authorize again, then use resume "
            "with this task_id, mode, and output path."
        )
    else:
        action = error.action
    return RunnerError(error.code, error.message, action, details)


def _finish_project(
    transport: HttpTransport,
    base_url: str,
    api_key: str,
    task_id: str,
    mode: str,
    output: Path,
    *,
    timeout: int,
    poll_interval: int,
    download_timeout: int,
) -> Dict[str, Any]:
    """Wait for and download one existing project without creating a new one."""
    try:
        project_status, result_url = _wait_for_project(
            transport,
            base_url,
            api_key,
            task_id,
            mode,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        _log(f"Downloading completed video to {output}...")
        file_size = transport.download(result_url, output, timeout=download_timeout)
    except RunnerError as error:
        raise _add_project_recovery(
            error,
            task_id=task_id,
            mode=mode,
            output=output,
        ) from error
    return {
        "task_id": task_id,
        "status": project_status,
        "local_path": str(output),
        "output_directory": str(output.parent),
        "file_size": file_size,
        "delivery": "attach_local_file",
    }


def command_run(args: argparse.Namespace, transport: HttpTransport) -> Dict[str, Any]:
    """Authorize, upload, create, poll, and download one web edit."""
    prepared = _prepare_run(args)
    state_path = args.state.expanduser().resolve()
    api_key, state = _exchange_authorization(state_path, transport)
    object_keys = [
        _upload_and_wait(
            transport,
            state["base_url"],
            api_key,
            path,
            upload_timeout=args.upload_timeout,
            asset_timeout=args.asset_timeout,
            asset_poll_interval=args.asset_poll_interval,
        )
        for path in prepared.files
    ]
    reference_key = None
    if prepared.reference_file is not None:
        reference_key = _upload_and_wait(
            transport,
            state["base_url"],
            api_key,
            prepared.reference_file,
            upload_timeout=args.upload_timeout,
            asset_timeout=args.asset_timeout,
            asset_poll_interval=args.asset_poll_interval,
        )
    task_id = _create_project(
        transport,
        state["base_url"],
        api_key,
        prepared,
        object_keys,
        reference_key,
    )
    return _finish_project(
        transport,
        state["base_url"],
        api_key,
        task_id,
        prepared.mode,
        prepared.output,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        download_timeout=args.download_timeout,
    )


def command_resume(args: argparse.Namespace, transport: HttpTransport) -> Dict[str, Any]:
    """Authorize and finish one existing project without creating a new project."""
    task_id = _validate_task_id(args.task_id)
    output = _validate_output(args.output)
    state_path = args.state.expanduser().resolve()
    api_key, state = _exchange_authorization(state_path, transport)
    return _finish_project(
        transport,
        state["base_url"],
        api_key,
        task_id,
        args.mode,
        output,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        download_timeout=args.download_timeout,
    )


def _positive_int(value: str) -> int:
    """Parse one positive command-line integer."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the web runner command-line parser."""
    parser = JsonArgumentParser(
        description="Dependency-free Sparki runner for browser and cloud agents.",
    )
    parser.add_argument("--version", action="version", version=RUNNER_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Check production API connectivity")
    probe.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL, help=argparse.SUPPRESS)

    authorize = subparsers.add_parser("authorize", help="Create or reuse browser authorization")
    authorize.add_argument("--channel", choices=sorted(ALLOWED_CHANNELS), default="codex")
    authorize.add_argument("--state", type=Path, required=True)
    authorize.add_argument("--force", action="store_true")
    authorize.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL, help=argparse.SUPPRESS)

    run = subparsers.add_parser("run", help="Upload, edit, and download a video")
    run.add_argument("files", nargs="+", type=Path)
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--mode", choices=("style-guided", "prompt-driven", "style-clone"), required=True)
    run.add_argument("--style", choices=sorted(STYLE_CATALOG))
    run.add_argument("--prompt")
    run.add_argument("--reference-url")
    run.add_argument("--reference-file", type=Path)
    run.add_argument("--aspect-ratio", choices=sorted(ALLOWED_ASPECT_RATIOS), default="9:16")
    run.add_argument("--duration-range", choices=sorted(VALID_DURATION_RANGES))
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--confirm-charge", action="store_true")
    run.add_argument("--upload-timeout", type=_positive_int, default=600)
    run.add_argument("--asset-timeout", type=_positive_int, default=1200)
    run.add_argument("--asset-poll-interval", type=_positive_int, default=10)
    run.add_argument("--timeout", type=_positive_int, default=3600)
    run.add_argument("--poll-interval", type=_positive_int, default=30)
    run.add_argument("--download-timeout", type=_positive_int, default=600)

    resume = subparsers.add_parser("resume", help="Finish an existing project without creating another")
    resume.add_argument("--state", type=Path, required=True)
    resume.add_argument("--task-id", required=True)
    resume.add_argument("--mode", choices=("style-guided", "prompt-driven", "style-clone"), required=True)
    resume.add_argument("--output", type=Path, required=True)
    resume.add_argument("--timeout", type=_positive_int, default=3600)
    resume.add_argument("--poll-interval", type=_positive_int, default=30)
    resume.add_argument("--download-timeout", type=_positive_int, default=600)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one command and emit exactly one JSON document on stdout."""
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        transport = HttpTransport()
        if args.command == "probe":
            result = command_probe(args, transport)
        elif args.command == "authorize":
            result = command_authorize(args, transport)
        elif args.command == "run":
            result = command_run(args, transport)
        elif args.command == "resume":
            result = command_resume(args, transport)
        else:
            raise RunnerError("INVALID_COMMAND", "Unknown command")
    except RunnerError as error:
        _emit_error(error)
        return 1
    except KeyboardInterrupt:
        _emit_error(
            RunnerError(
                "INTERRUPTED",
                "The Sparki web runner was interrupted",
                "Run the command again when ready.",
            )
        )
        return 130
    except Exception as exc:
        _emit_error(
            RunnerError(
                "RUNNER_ERROR",
                "The Sparki web runner encountered an unexpected error",
                "Retry once. If it persists, report the error type to Sparki support.",
                {"reason": type(exc).__name__},
            )
        )
        return 1
    _emit_success(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
