"""Cryptographic security utilities for token hashing and API key generation."""
import hashlib
import hmac
import secrets


def hash_secret(secret: str) -> str:
    """Compute constant SHA-256 hash of a token or credential."""
    return hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()


def verify_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Compare a plain secret with its stored SHA-256 hash using constant-time comparison."""
    computed = hash_secret(plain_secret)
    return hmac.compare_digest(computed, hashed_secret)


def generate_api_key(prefix: str = "edc_key_") -> str:
    """Generate high-entropy random per-device API credential."""
    return f"{prefix}{secrets.token_urlsafe(32)}"


def generate_enrollment_token(prefix: str = "edc_enroll_") -> str:
    """Generate high-entropy one-time enrollment token."""
    return f"{prefix}{secrets.token_urlsafe(24)}"
