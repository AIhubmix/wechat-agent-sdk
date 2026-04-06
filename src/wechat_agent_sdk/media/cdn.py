"""iLink CDN upload and download for encrypted media."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid as uuid_lib

import httpx

from .crypto import decrypt, encrypt, decode_aes_key, generate_aes_key, cipher_size

logger = logging.getLogger(__name__)

CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"


async def download_media(
    http_client: httpx.AsyncClient,
    encrypt_query_param: str,
    aes_key_b64: str,
    aeskey_hex: str = "",
) -> bytes:
    """
    Download and decrypt a media file from the iLink CDN.

    Args:
        http_client: An httpx async client.
        encrypt_query_param: The CDN query param from the message.
        aes_key_b64: Base64-encoded AES key (from media.aes_key).
        aeskey_hex: Hex AES key (from image_item.aeskey), takes priority.

    Returns:
        Decrypted file bytes.
    """
    url = f"{CDN_BASE}?encrypted_query_param={encrypt_query_param}"
    resp = await http_client.get(url, timeout=60.0)
    resp.raise_for_status()

    key = decode_aes_key(aes_key_b64, aeskey_hex)
    return decrypt(resp.content, key)


async def upload_media(
    bot_client,  # ILinkBotClient
    http_client: httpx.AsyncClient,
    to_user_id: str,
    file_data: bytes,
    media_type: int,
    file_name: str = "",
) -> dict:
    """
    Encrypt and upload a media file to the iLink CDN.

    Args:
        bot_client: ILinkBotClient instance (for get_upload_url).
        http_client: An httpx async client (for CDN upload).
        to_user_id: Recipient user ID.
        file_data: Raw file bytes.
        media_type: 1=IMAGE, 2=VIDEO, 3=FILE, 4=VOICE.
        file_name: Original file name.

    Returns:
        CDN media reference dict for use in sendmessage item_list::

            {"encrypt_query_param": str, "aes_key": str, "encrypt_type": 1}
    """
    key = generate_aes_key()
    encrypted = encrypt(file_data, key)
    raw_md5 = hashlib.md5(file_data).hexdigest()
    filekey = uuid_lib.uuid4().hex

    # Step 1: get pre-signed upload URL
    upload_info = await bot_client.get_upload_url(
        filekey=filekey,
        media_type=media_type,
        to_user_id=to_user_id,
        raw_size=len(file_data),
        raw_file_md5=raw_md5,
        file_size=len(encrypted),
        aes_key_hex=key.hex(),
    )
    upload_param = upload_info.get("upload_param", "")
    if not upload_param:
        raise RuntimeError(f"getuploadurl returned no upload_param: {upload_info}")

    # Step 2: upload encrypted data to CDN
    upload_url = f"{CDN_BASE}/upload?encrypted_query_param={upload_param}&filekey={filekey}"
    resp = await http_client.post(
        upload_url,
        content=encrypted,
        headers={"Content-Type": "application/octet-stream"},
        timeout=120.0,
    )
    resp.raise_for_status()

    # Step 3: extract CDN reference from response
    cdn_param = resp.headers.get("x-encrypted-param", "")
    if not cdn_param:
        raise RuntimeError("CDN upload failed: no x-encrypted-param in response headers")

    aes_key_b64 = base64.b64encode(key).decode()

    return {
        "encrypt_query_param": cdn_param,
        "aes_key": aes_key_b64,
        "encrypt_type": 1,
    }
