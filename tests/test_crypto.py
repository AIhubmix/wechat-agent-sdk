"""Test AES-128-ECB crypto + dual-format key decoding."""

import base64
import pytest

from wechat_agent_sdk.media.crypto import (
    cipher_size,
    decode_aes_key,
    decrypt,
    encrypt,
    generate_aes_key,
)


def test_encrypt_decrypt_roundtrip():
    key = generate_aes_key()
    assert len(key) == 16

    plaintext = b"hello wechat agent sdk"
    ciphertext = encrypt(plaintext, key)
    assert ciphertext != plaintext

    decrypted = decrypt(ciphertext, key)
    assert decrypted == plaintext


def test_encrypt_decrypt_empty():
    key = generate_aes_key()
    ciphertext = encrypt(b"", key)
    assert decrypt(ciphertext, key) == b""


def test_encrypt_decrypt_block_aligned():
    """Data that's exactly 16 bytes should still work (PKCS7 adds a full block)."""
    key = generate_aes_key()
    data = b"0123456789abcdef"  # exactly 16 bytes
    assert decrypt(encrypt(data, key), key) == data


def test_encrypt_decrypt_large():
    key = generate_aes_key()
    data = b"x" * 100_000
    assert decrypt(encrypt(data, key), key) == data


def test_cipher_size():
    assert cipher_size(0) == 16       # ceil((0+1)/16)*16 = 16
    assert cipher_size(1) == 16       # ceil((1+1)/16)*16 = 16
    assert cipher_size(15) == 16      # ceil((15+1)/16)*16 = 16
    assert cipher_size(16) == 32      # ceil((16+1)/16)*16 = 32
    assert cipher_size(31) == 32      # ceil((31+1)/16)*16 = 32
    assert cipher_size(32) == 48


def test_decode_aes_key_format_a():
    """Format A: base64(raw 16 bytes)."""
    raw_key = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff"
    b64 = base64.b64encode(raw_key).decode()
    assert decode_aes_key(b64) == raw_key


def test_decode_aes_key_format_b():
    """Format B: base64(hex string) → 32 ASCII bytes → hex decode → 16 bytes."""
    raw_key = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff"
    hex_str = raw_key.hex()  # "00112233445566778899aabbccddeeff"
    b64_of_hex = base64.b64encode(hex_str.encode("ascii")).decode()
    assert decode_aes_key(b64_of_hex) == raw_key


def test_decode_aes_key_hex_priority():
    """aeskey_hex (image_item field) takes priority over aes_key_b64."""
    hex_key = "00112233445566778899aabbccddeeff"
    expected = bytes.fromhex(hex_key)

    # Even with a different b64 key, hex should win
    fake_b64 = base64.b64encode(b"\xff" * 16).decode()
    assert decode_aes_key(fake_b64, aeskey_hex=hex_key) == expected


def test_decode_aes_key_no_key_raises():
    with pytest.raises(ValueError, match="No AES key"):
        decode_aes_key("")


def test_decode_aes_key_invalid_length_raises():
    # 8 bytes is neither 16 nor 32
    bad_b64 = base64.b64encode(b"\x00" * 8).decode()
    with pytest.raises(ValueError, match="Unexpected AES key length"):
        decode_aes_key(bad_b64)
