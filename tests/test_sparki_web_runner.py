"""Tests for the dependency-free Sparki web runner."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


RUNNER_PATH = (
    Path(__file__).parents[1]
    / "plugins"
    / "sparki-video-editor"
    / "skills"
    / "sparki-video-editor"
    / "scripts"
    / "sparki_web_runner.py"
)
TASK_ID = "550e8400-e29b-41d4-a716-446655440000"
SPEC = importlib.util.spec_from_file_location("sparki_web_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class FakeTransport:
    """Return scripted JSON responses without making network requests."""

    def __init__(self, responses: list[Tuple[int, Dict[str, Any]]]) -> None:
        """Initialize the transport with ordered responses."""
        self.responses = list(responses)
        self.requests: list[Tuple[str, str, Optional[Mapping[str, Any]]]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, Dict[str, str], Dict[str, Any]]:
        """Record one request and return its scripted response."""
        del headers, timeout
        self.requests.append((method, url, payload))
        status, response = self.responses.pop(0)
        return status, {}, response


class FakeResponse:
    """Provide the HTTPResponse subset used by the runner."""

    def __init__(self, status: int, body: bytes, *, fail_after_first: bool = False) -> None:
        """Initialize a bounded fake response body."""
        self.status = status
        self.body = body
        self.offset = 0
        self.read_count = 0
        self.fail_after_first = fail_after_first

    def read(self, size: Optional[int] = None) -> bytes:
        """Read one body chunk and optionally simulate a network failure."""
        self.read_count += 1
        if self.fail_after_first and self.read_count > 1:
            raise OSError("simulated disconnect")
        if size is None or size < 0:
            size = len(self.body) - self.offset
        result = self.body[self.offset : self.offset + size]
        self.offset += len(result)
        return result

    def getheader(self, name: str) -> Optional[str]:
        """Return no optional response headers."""
        del name
        return None


class FakeConnection:
    """Provide the HTTPSConnection subset used by streaming methods."""

    def __init__(self, response: FakeResponse) -> None:
        """Initialize a connection with one response."""
        self.response = response
        self.sent_sizes: list[int] = []

    def putrequest(self, method: str, target: str) -> None:
        """Accept a streaming request line."""
        del method, target

    def putheader(self, name: str, value: str) -> None:
        """Accept one streaming request header."""
        del name, value

    def endheaders(self) -> None:
        """Finish fake request headers."""
        return None

    def send(self, data: bytes) -> None:
        """Record individual streaming write sizes."""
        self.sent_sizes.append(len(data))

    def request(
        self,
        method: str,
        target: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        """Accept a regular request."""
        del method, target, headers

    def getresponse(self) -> FakeResponse:
        """Return the configured response."""
        return self.response

    def close(self) -> None:
        """Close the fake connection."""
        return None


class WorkflowTransport:
    """Simulate one successful end-to-end API workflow."""

    def __init__(self, secret: str) -> None:
        """Initialize the workflow with an in-memory credential."""
        self.secret = secret
        self.project_payload: Optional[Mapping[str, Any]] = None
        self.project_create_count = 0

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, Dict[str, str], Dict[str, Any]]:
        """Return the response associated with one workflow endpoint."""
        del method, headers, timeout
        if url.endswith("/api/v1/cli-auth/token"):
            return 200, {}, {
                "code": 200,
                "data": {"api_key": self.secret, "channel": "codex"},
            }
        if "/api/v1/assets/user_assets?" in url:
            return 200, {}, {
                "code": 200,
                "data": {"assets": [{"object_key": "assets/source.mp4", "status": 1}]},
            }
        if url.endswith("/api/v1/projects/"):
            self.project_create_count += 1
            self.project_payload = payload
            return 200, {}, {"code": 200, "data": {"task_id": TASK_ID}}
        if url.endswith(f"/api/v1/projects/task/{TASK_ID}"):
            return 200, {}, {
                "code": 200,
                "data": {
                    "status": "COMPLETED",
                    "materials": [{"url": "https://cdn.example.com/result.mp4"}],
                },
            }
        raise AssertionError(f"Unexpected URL: {url}")

    def upload_file(
        self,
        url: str,
        file_path: Path,
        *,
        headers: Mapping[str, str],
        timeout: int,
    ) -> Tuple[int, Dict[str, Any]]:
        """Return one processed source asset key."""
        del url, file_path, headers, timeout
        return 200, {"code": 200, "data": {"object_key": "assets/source.mp4"}}

    def download(self, url: str, output_path: Path, *, timeout: int) -> int:
        """Write a small fake result at the requested path."""
        del url, timeout
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"result")
        return len(b"result")


class WebRunnerTests(unittest.TestCase):
    """Exercise authorization, validation, and payload security boundaries."""

    def test_authorize_writes_private_state_without_api_key(self) -> None:
        """Persist only short-lived PKCE state and reuse the same request."""
        authorization_id = "A" * 43
        transport = FakeTransport(
            [
                (
                    201,
                    {
                        "code": 201,
                        "message": "created",
                        "data": {
                            "authorization_id": authorization_id,
                            "verification_uri_complete": (
                                "https://sparki.io/connect/codex/start?"
                                f"authorization_id={authorization_id}"
                            ),
                            "expires_in": 600,
                            "interval": 2,
                        },
                    },
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "auth" / "state.json"
            args = Namespace(
                state=state_path,
                channel="codex",
                force=False,
                api_base_url=runner.DEFAULT_API_BASE_URL,
            )

            first = runner.command_authorize(args, transport)
            second = runner.command_authorize(args, transport)

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(len(transport.requests), 1)
            self.assertNotIn("api_key", payload)
            self.assertNotIn("SPARKI_API_KEY", payload)
            if os.name != "nt":
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

    def test_pending_exchange_preserves_state_and_same_url(self) -> None:
        """Keep one authorization alive while browser approval is pending."""
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._valid_state()
            runner._write_state(state_path, state)
            transport = FakeTransport(
                [
                    (
                        400,
                        {
                            "code": 400,
                            "message": "Authorization is pending",
                            "data": {"code": "AUTHORIZATION_PENDING", "interval": 3},
                        },
                    )
                ]
            )

            with self.assertRaises(runner.RunnerError) as context:
                runner._exchange_authorization(state_path, transport)

            self.assertEqual(context.exception.code, "AUTHORIZATION_PENDING")
            self.assertEqual(
                context.exception.details["authorization_url"],
                state["verification_url"],
            )
            self.assertTrue(state_path.exists())

    def test_successful_exchange_never_persists_api_key(self) -> None:
        """Return the credential in memory and delete the temporary state."""
        secret = "sk_live_" + "s" * 43
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self._valid_state()
            runner._write_state(state_path, state)
            transport = FakeTransport(
                [
                    (
                        200,
                        {
                            "code": 200,
                            "message": "success",
                            "data": {"api_key": secret, "channel": "codex"},
                        },
                    )
                ]
            )

            api_key, returned_state = runner._exchange_authorization(state_path, transport)

            self.assertEqual(api_key, secret)
            self.assertEqual(returned_state["channel"], "codex")
            self.assertFalse(state_path.exists())

    def test_rejects_non_sparki_api_origin(self) -> None:
        """Prevent hidden configuration from redirecting credentials."""
        with self.assertRaises(runner.RunnerError) as context:
            runner._api_url("https://example.com", "/api/v1/assets/upload")

        self.assertEqual(context.exception.code, "INVALID_API_ORIGIN")

    def test_rejects_spoofed_authorization_url(self) -> None:
        """Require the exact sparki.io channel path and query."""
        authorization_id = "A" * 43
        with self.assertRaises(runner.RunnerError):
            runner._validate_verification_url(
                "https://sparki.io.evil.example/connect/codex/start?"
                f"authorization_id={authorization_id}",
                "codex",
                authorization_id,
            )

    def test_classifies_top_level_backend_codes(self) -> None:
        """Map top-level numeric envelope codes to stable runner errors."""
        cases = (
            (413, "Insufficient storage space", "STORAGE_FULL"),
            (413, "File too large", "FILE_TOO_LARGE"),
            (402, "Insufficient credits", "QUOTA_EXCEEDED"),
            (429, "Too many concurrent projects", "CONCURRENT_LIMIT"),
        )
        for code, message, expected in cases:
            with self.subTest(code=code, message=message):
                with self.assertRaises(runner.RunnerError) as context:
                    runner._unwrap_api_response(
                        200,
                        {"code": code, "message": message, "data": None},
                        default_error="REQUEST_FAILED",
                    )
                self.assertEqual(context.exception.code, expected)

    def test_classifies_http_status_when_envelope_code_is_stale(self) -> None:
        """Use the transport status when a proxy preserves a stale envelope code."""
        with self.assertRaises(runner.RunnerError) as context:
            runner._unwrap_api_response(
                413,
                {"code": 200, "message": "Request entity too large", "data": None},
                default_error="UPLOAD_FAILED",
            )

        self.assertEqual(context.exception.code, "FILE_TOO_LARGE")

    def test_multipart_filename_preserves_ascii_and_falls_back_for_unicode(self) -> None:
        """Keep useful ASCII names without emitting Unicode in filename fallback."""
        self.assertEqual(
            runner._ascii_multipart_filename(Path("my clip.mp4")),
            "my clip.mp4",
        )
        self.assertEqual(
            runner._ascii_multipart_filename(Path("爬山素材.mov")),
            "upload.mov",
        )

    def test_invalid_arguments_return_one_json_error(self) -> None:
        """Keep argparse failures inside the runner's machine-readable contract."""
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = runner.main(["run"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")

    def test_run_validation_happens_before_authorization_exchange(self) -> None:
        """Reject unconfirmed paid work before consuming browser approval."""
        args = Namespace(confirm_charge=False)

        with self.assertRaises(runner.RunnerError) as context:
            runner.command_run(args, FakeTransport([]))

        self.assertEqual(context.exception.code, "CONFIRMATION_REQUIRED")

    def test_prompt_driven_payload_matches_cli_contract(self) -> None:
        """Build the same prompt-driven payload expected by the backend."""
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"video")
            args = Namespace(
                confirm_charge=True,
                files=[video],
                reference_file=None,
                reference_url=None,
                mode="prompt-driven",
                style=None,
                prompt="Make a concise highlight reel",
                duration_range="30s~60s",
                aspect_ratio="9:16",
                output=Path(directory) / "output.mp4",
            )

            prepared = runner._prepare_run(args)

            self.assertEqual(prepared.project_body["tags"], ["71"])
            self.assertEqual(prepared.project_body["agent_type"], "vlog_skill")
            self.assertEqual(
                prepared.project_body["generation_preferences"],
                {"aspect_ratio": "9:16", "duration_range": "30s~60s"},
            )

    def test_style_clone_requires_exactly_one_reference(self) -> None:
        """Reject ambiguous style-clone reference input."""
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"video")
            args = Namespace(
                confirm_charge=True,
                files=[video],
                reference_file=None,
                reference_url=None,
                mode="style-clone",
                style=None,
                prompt=None,
                duration_range=None,
                aspect_ratio="9:16",
                output=Path(directory) / "output.mp4",
            )

            with self.assertRaises(runner.RunnerError) as context:
                runner._prepare_run(args)

            self.assertEqual(context.exception.code, "INVALID_REFERENCE")

    def test_output_cannot_overwrite_source_video(self) -> None:
        """Reject an output path that would destroy the uploaded source."""
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"video")
            args = Namespace(
                confirm_charge=True,
                files=[video],
                reference_file=None,
                reference_url=None,
                mode="style-guided",
                style="vlog/daily",
                prompt=None,
                duration_range=None,
                aspect_ratio="9:16",
                output=video,
            )

            with self.assertRaises(runner.RunnerError) as context:
                runner._prepare_run(args)

            self.assertEqual(context.exception.code, "INVALID_OUTPUT")

    def test_upload_streams_file_in_bounded_chunks(self) -> None:
        """Avoid buffering a large browser attachment in process memory."""
        response_body = json.dumps(
            {"code": 200, "data": {"object_key": "assets/source.mp4"}}
        ).encode("utf-8")
        connection = FakeConnection(FakeResponse(200, response_body))
        transport = runner.HttpTransport()
        transport._connection = lambda *_args, **_kwargs: (connection, "/upload")
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"x" * (runner.UPLOAD_CHUNK_SIZE * 2 + 17))

            status, payload = transport.upload_file(
                "https://agent-api.sparki.io/api/v1/assets/upload",
                video,
                headers={"X-API-Key": "secret"},
                timeout=30,
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["object_key"], "assets/source.mp4")
        file_chunks = connection.sent_sizes[1:-1]
        self.assertEqual(file_chunks, [runner.UPLOAD_CHUNK_SIZE, runner.UPLOAD_CHUNK_SIZE, 17])

    def test_failed_download_preserves_existing_output_and_removes_temp(self) -> None:
        """Leave no corrupt final file when a streaming download fails."""
        connection = FakeConnection(
            FakeResponse(
                200,
                b"x" * (runner.DOWNLOAD_CHUNK_SIZE + 1),
                fail_after_first=True,
            )
        )
        transport = runner.HttpTransport()
        transport._connection = lambda *_args, **_kwargs: (connection, "/result")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.write_bytes(b"existing")

            with self.assertRaises(runner.RunnerError) as context:
                transport.download("https://cdn.example.com/result.mp4", output, timeout=30)

            self.assertEqual(context.exception.code, "DOWNLOAD_FAILED")
            self.assertEqual(output.read_bytes(), b"existing")
            self.assertEqual(
                [path for path in Path(directory).iterdir() if path.suffix == ".part"],
                [],
            )

    def test_successful_command_run_matches_end_to_end_contract(self) -> None:
        """Complete auth, upload, project creation, polling, and delivery."""
        secret = "sk_live_" + "s" * 43
        transport = WorkflowTransport(secret)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            state_path = root / "state.json"
            runner._write_state(state_path, self._valid_state())
            output = root / "sparki-output" / "edited.mp4"
            args = Namespace(
                confirm_charge=True,
                files=[source],
                reference_file=None,
                reference_url=None,
                mode="style-guided",
                style="clips/highlight-reel",
                prompt=None,
                duration_range=None,
                aspect_ratio="9:16",
                output=output,
                state=state_path,
                upload_timeout=30,
                asset_timeout=30,
                asset_poll_interval=1,
                timeout=30,
                poll_interval=1,
                download_timeout=30,
            )

            result = runner.command_run(args, transport)

            self.assertFalse(state_path.exists())
            self.assertEqual(output.read_bytes(), b"result")
            self.assertEqual(result["task_id"], TASK_ID)
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn("result_url", result)
            assert transport.project_payload is not None
            self.assertEqual(
                transport.project_payload["resources"],
                [{"idx": 0, "s3_object_key": "assets/source.mp4"}],
            )
            self.assertEqual(transport.project_payload["tags"], ["28"])

    def test_resume_downloads_existing_project_without_creating_another(self) -> None:
        """Resume only status polling and delivery after fresh authorization."""
        secret = "sk_live_" + "s" * 43
        transport = WorkflowTransport(secret)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            runner._write_state(state_path, self._valid_state())
            output = root / "sparki-output" / "resumed.mp4"
            args = Namespace(
                state=state_path,
                task_id=TASK_ID,
                mode="style-guided",
                output=output,
                timeout=30,
                poll_interval=1,
                download_timeout=30,
            )

            result = runner.command_resume(args, transport)

            self.assertEqual(result["task_id"], TASK_ID)
            self.assertEqual(output.read_bytes(), b"result")
            self.assertEqual(transport.project_create_count, 0)

    def test_post_creation_failure_exposes_safe_resume_context(self) -> None:
        """Return recovery fields instead of encouraging duplicate paid work."""
        error = runner.RunnerError(
            "DOWNLOAD_FAILED",
            "The completed video could not be downloaded",
        )

        recovered = runner._add_project_recovery(
            error,
            task_id=TASK_ID,
            mode="prompt-driven",
            output=Path("sparki-output/result.mp4").resolve(),
        )

        self.assertEqual(recovered.details["task_id"], TASK_ID)
        self.assertEqual(recovered.details["mode"], "prompt-driven")
        self.assertIn("Do not run the full edit again", recovered.action)

    @staticmethod
    def _valid_state() -> Dict[str, Any]:
        """Build one valid unexpired authorization state."""
        authorization_id = "A" * 43
        return {
            "schema_version": 1,
            "channel": "codex",
            "base_url": runner.DEFAULT_API_BASE_URL,
            "authorization_id": authorization_id,
            "code_verifier": "v" * 64,
            "verification_url": (
                "https://sparki.io/connect/codex/start?"
                f"authorization_id={authorization_id}"
            ),
            "expires_at": time.time() + 600,
            "interval": 2,
        }


if __name__ == "__main__":
    unittest.main()
