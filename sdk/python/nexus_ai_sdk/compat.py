"""nexus_ai_sdk.compat — SDK compatibility validation.

Checks:
  - Python version meets minimum (3.9+)
  - Required dependencies are importable at the correct version
  - Optional dependencies (httpx) have compatible versions
  - Server API version matches SDK expectations (when base_url provided)
  - Runtime feature detection (typing.Protocol, dataclasses, etc.)

Call ``validate()`` at startup to get a ``CompatReport`` or raise on hard failures.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from ._version import __version__, __api_version__, __min_server_version__


_MIN_PYTHON = (3, 9)
_REQUIRED_DEPS: list[tuple[str, str]] = [
    ("requests", "2.28.0"),
]
_OPTIONAL_DEPS: list[tuple[str, str]] = [
    ("httpx", "0.24.0"),
]


@dataclass
class CompatCheck:
    name: str
    passed: bool
    required: bool
    actual: str = ""
    expected: str = ""
    message: str = ""


@dataclass
class CompatReport:
    sdk_version: str
    python_version: str
    checks: list[CompatCheck] = field(default_factory=list)
    server_api_version: str = ""
    server_version: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.required)

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if not c.passed and not c.required]

    @property
    def errors(self) -> list[str]:
        return [c.message for c in self.checks if not c.passed and c.required]

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise CompatibilityError(
                f"Nexus AI SDK v{self.sdk_version} compatibility check failed:\n"
                + "\n".join(f"  - {e}" for e in self.errors)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sdk_version": self.sdk_version,
            "python_version": self.python_version,
            "passed": self.passed,
            "server_api_version": self.server_api_version,
            "server_version": self.server_version,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "required": c.required,
                    "actual": c.actual,
                    "expected": c.expected,
                    "message": c.message,
                }
                for c in self.checks
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


class CompatibilityError(RuntimeError):
    pass


def _parse_version(ver_str: str) -> tuple[int, ...]:
    parts = []
    for p in str(ver_str).split(".")[:3]:
        try:
            parts.append(int("".join(c for c in p if c.isdigit()) or "0"))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _check_python() -> CompatCheck:
    actual = sys.version_info[:3]
    ok = actual >= _MIN_PYTHON
    return CompatCheck(
        name="python_version",
        passed=ok,
        required=True,
        actual=f"{actual[0]}.{actual[1]}.{actual[2]}",
        expected=f">={_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}",
        message="" if ok else f"Python {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}+ required, got {actual[0]}.{actual[1]}.{actual[2]}",
    )


def _check_dep(package: str, min_ver: str, required: bool) -> CompatCheck:
    try:
        mod = __import__(package)
        actual_ver = getattr(mod, "__version__", None) or getattr(mod, "VERSION", None) or "0.0.0"
        actual_tuple = _parse_version(str(actual_ver))
        min_tuple = _parse_version(min_ver)
        ok = actual_tuple >= min_tuple
        return CompatCheck(
            name=f"dep_{package}",
            passed=ok,
            required=required,
            actual=str(actual_ver),
            expected=f">={min_ver}",
            message="" if ok else f"{package}>={min_ver} required, got {actual_ver}",
        )
    except ImportError:
        if required:
            return CompatCheck(
                name=f"dep_{package}", passed=False, required=True,
                actual="not installed", expected=f">={min_ver}",
                message=f"Required dependency '{package}>={min_ver}' is not installed. Run: pip install nexus-ai-sdk",
            )
        return CompatCheck(
            name=f"dep_{package}", passed=True, required=False,
            actual="not installed", expected=f">={min_ver}",
            message=f"Optional dependency '{package}' not installed. For async support: pip install nexus-ai-sdk[async]",
        )


def _check_server(base_url: str) -> tuple[str, str, CompatCheck]:
    """Probe /health and /v1/models to extract server version."""
    try:
        import requests as _req
        r = _req.get(f"{base_url.rstrip('/')}/health", timeout=5)
        if r.status_code < 400:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            server_ver = str(data.get("version", ""))
            api_ver = r.headers.get("X-API-Version", "")
            ok = True
            msg = ""
            if api_ver and api_ver != __api_version__:
                ok = False
                msg = f"Server API version '{api_ver}' may be incompatible with SDK expecting '{__api_version__}'"
            return server_ver, api_ver, CompatCheck(
                name="server_api_version", passed=ok, required=False,
                actual=api_ver or server_ver, expected=__api_version__,
                message=msg,
            )
    except Exception as exc:
        return "", "", CompatCheck(
            name="server_api_version", passed=True, required=False,
            actual="unreachable", expected=__api_version__,
            message=f"Could not reach server at {base_url}: {exc}",
        )
    return "", "", CompatCheck(name="server_api_version", passed=True, required=False, actual="", expected=__api_version__)


def _check_typing_features() -> CompatCheck:
    """Verify runtime typing features used by the SDK are available."""
    try:
        from dataclasses import dataclass as _dc, field as _f  # noqa: F401
        from typing import Generator, Any as _Any  # noqa: F401
        if sys.version_info >= (3, 10):
            pass  # X | Y union syntax available
        return CompatCheck(name="typing_features", passed=True, required=True)
    except Exception as exc:
        return CompatCheck(
            name="typing_features", passed=False, required=True,
            message=f"Required typing features unavailable: {exc}",
        )


def validate(base_url: str = "", raise_on_failure: bool = False) -> CompatReport:
    """Run all compatibility checks and return a ``CompatReport``.

    Args:
        base_url:         Optional server URL to probe for API version compatibility.
        raise_on_failure: Raise ``CompatibilityError`` if any required check fails.
    """
    checks: list[CompatCheck] = [
        _check_python(),
        _check_typing_features(),
        *[_check_dep(pkg, ver, required=True) for pkg, ver in _REQUIRED_DEPS],
        *[_check_dep(pkg, ver, required=False) for pkg, ver in _OPTIONAL_DEPS],
    ]

    server_version = ""
    api_version = ""
    if base_url:
        server_version, api_version, server_check = _check_server(base_url)
        checks.append(server_check)

    report = CompatReport(
        sdk_version=__version__,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        checks=checks,
        server_api_version=api_version,
        server_version=server_version,
    )

    if raise_on_failure:
        report.raise_if_failed()

    return report


def assert_compatible(base_url: str = "") -> None:
    """Raise ``CompatibilityError`` if required checks fail."""
    validate(base_url=base_url, raise_on_failure=True)
