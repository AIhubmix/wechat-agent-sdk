"""AES-128-ECB encryption/decryption for iLink CDN media."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding


def decode_aes_key(aes_key_b64: str, aeskey_hex: str = "") -> bytes:
    """
    Decode an iLink AES key, handling the dual-format quirk.

    Priority: ``aeskey_hex`` (image_item-specific, 32-char hex string)
    over ``aes_key_b64`` (generic media field).

    Format A: base64(raw 16 bytes) -> decode to 16 bytes, use directly.
    Format B: base64(hex string)   -> decode to 32 ASCII bytes, hex-decode to 16.
    """
    if aeskey_hex and len(aeskey_hex) == 32:
        return bytes.fromhex(aeskey_hex)

    if not aes_key_b64:
        raise ValueError("No AES key provided")

    raw = base64.b64decode(aes_key_b64)
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            pass
    raise ValueError(f"Unexpected AES key length after base64 decode: {len(raw)}")


def generate_aes_key() -> bytes:
    """Generate a random 16-byte AES key."""
    return os.urandom(16)


def encrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-ECB encrypt with PKCS7 padding."""
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def decrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-ECB decrypt and remove PKCS7 padding."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    dec = cipher.decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def cipher_size(raw_size: int) -> int:
    """Calculate ciphertext size: ceil((raw_size + 1) / 16) * 16."""
    return ((raw_size + 1 + 15) // 16) * 16
