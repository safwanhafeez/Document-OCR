from __future__ import annotations

import os
import time
from http.server import BaseHTTPRequestHandler
from threading import Lock
from typing import Dict, TypedDict


class RateLimitResult(TypedDict):
    allowed: bool
    remaining: int
    reset_ms: int
    retry_after_seconds: int
    limit: int
    blocked: bool


class _WindowState(TypedDict):
    count: int
    window_start: float


class _AbuseState(TypedDict):
    count: int
    window_start: float
    blocked_until: float


ABUSE_WINDOW_MS = 10 * 60 * 1000
ABUSE_THRESHOLD = 50
ABUSE_BLOCK_MS = 60 * 60 * 1000

_window_map: Dict[str, _WindowState] = {}
_abuse_map: Dict[str, _AbuseState] = {}
_lock = Lock()


def _parse_positive_int(raw: str, fallback: int) -> int:
    if not raw:
        return fallback
    try:
        parsed = int(raw)
    except ValueError:
        return fallback
    return parsed if parsed > 0 else fallback


def get_rate_limit_config() -> Dict[str, int]:
    return {
        "max": _parse_positive_int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", ""), 10),
        "window_ms": _parse_positive_int(os.environ.get("RATE_LIMIT_WINDOW_MS", ""), 60000),
    }


def get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real = handler.headers.get("X-Real-IP")
    if real and real.strip():
        return real.strip()
    return "anonymous"


def _prune(now_ms: float, window_ms: int) -> None:
    expired_windows = [
        key for key, state in _window_map.items()
        if now_ms - state["window_start"] >= window_ms
    ]
    for key in expired_windows:
        _window_map.pop(key, None)

    expired_abuse = []
    for key, state in _abuse_map.items():
        if state["blocked_until"] > 0 and state["blocked_until"] <= now_ms:
            expired_abuse.append(key)
        elif state["blocked_until"] == 0 and now_ms - state["window_start"] >= ABUSE_WINDOW_MS:
            expired_abuse.append(key)
    for key in expired_abuse:
        _abuse_map.pop(key, None)


def _evaluate_abuse(key: str, now_ms: float) -> RateLimitResult | None:
    existing = _abuse_map.get(key)
    if existing is None:
        _abuse_map[key] = {
            "count": 1,
            "window_start": now_ms,
            "blocked_until": 0.0,
        }
        return None
    if existing["blocked_until"] > now_ms:
        return {
            "allowed": False,
            "remaining": 0,
            "reset_ms": int(existing["blocked_until"]),
            "retry_after_seconds": max(1, int((existing["blocked_until"] - now_ms) / 1000) + 1),
            "limit": ABUSE_THRESHOLD,
            "blocked": True,
        }
    if now_ms - existing["window_start"] >= ABUSE_WINDOW_MS:
        existing["count"] = 1
        existing["window_start"] = now_ms
        existing["blocked_until"] = 0.0
        return None
    existing["count"] += 1
    if existing["count"] > ABUSE_THRESHOLD:
        existing["blocked_until"] = now_ms + ABUSE_BLOCK_MS
        return {
            "allowed": False,
            "remaining": 0,
            "reset_ms": int(existing["blocked_until"]),
            "retry_after_seconds": 3600,
            "limit": ABUSE_THRESHOLD,
            "blocked": True,
        }
    return None


def check_rate_limit(handler: BaseHTTPRequestHandler) -> RateLimitResult:
    now_ms = time.time() * 1000
    config = get_rate_limit_config()
    max_requests = config["max"]
    window_ms = config["window_ms"]

    with _lock:
        _prune(now_ms, window_ms)
        ip = get_client_ip(handler)

        abuse = _evaluate_abuse(ip, now_ms)
        if abuse is not None:
            return abuse

        state = _window_map.get(ip)
        if state is None or now_ms - state["window_start"] >= window_ms:
            _window_map[ip] = {"count": 1, "window_start": now_ms}
            return {
                "allowed": True,
                "remaining": max(0, max_requests - 1),
                "reset_ms": int(now_ms + window_ms),
                "retry_after_seconds": 0,
                "limit": max_requests,
                "blocked": False,
            }

        state["count"] += 1
        remaining = max(0, max_requests - state["count"])
        reset_ms = int(state["window_start"] + window_ms)

        if state["count"] > max_requests:
            retry_after = max(1, int((reset_ms - now_ms) / 1000) + 1)
            return {
                "allowed": False,
                "remaining": 0,
                "reset_ms": reset_ms,
                "retry_after_seconds": retry_after,
                "limit": max_requests,
                "blocked": False,
            }

        return {
            "allowed": True,
            "remaining": remaining,
            "reset_ms": reset_ms,
            "retry_after_seconds": 0,
            "limit": max_requests,
            "blocked": False,
        }


def rate_limit_headers(result: RateLimitResult) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "X-RateLimit-Limit": str(result["limit"]),
        "X-RateLimit-Remaining": str(result["remaining"]),
        "X-RateLimit-Reset": str(result["reset_ms"] // 1000),
    }
    if not result["allowed"]:
        headers["Retry-After"] = str(result["retry_after_seconds"])
    return headers
