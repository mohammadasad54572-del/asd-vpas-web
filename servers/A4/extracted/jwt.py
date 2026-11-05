import time
import json
import base64
import logging

import httpx
from Crypto.Cipher import AES

from google.protobuf import json_format
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
from google.protobuf.message import Message

from flask import Flask, request, jsonify
from flask_cors import CORS

log = logging.getLogger("werkzeug")
log.disabled = True

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 6, 30, 0, "", "FreeFire.proto",
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x0e\x46reeFire.proto"c\n\x08LoginReq\x12\x0f\n\x07open_id\x18\x16 \x01(\t'
    b'\x12\x14\n\x0copen_id_type\x18\x17 \x01(\t\x12\x13\n\x0blogin_token\x18\x1d '
    b'\x01(\t\x12\x1b\n\x13orign_platform_type\x18\x63 \x01(\t"]\n\x10\x42lacklist'
    b'InfoRes\x12\x1e\n\nban_reason\x18\x01 \x01(\x0e\x32\n.BanReason\x12\x17\n'
    b'\x0f\x65xpire_duration\x18\x02 \x01(\r\x12\x10\n\x08\x62\x61n_time\x18\x03 '
    b'\x01(\r"f\n\x0eLoginQueueInfo\x12\r\n\x05\x61llow\x18\x01 \x01(\x08\x12'
    b'\x16\n\x0equeue_position\x18\x02 \x01(\r\x12\x16\n\x0eneed_wait_secs\x18'
    b'\x03 \x01(\r\x12\x15\n\rqueue_is_full\x18\x04 \x01(\x08"\xa0\x03\n\x08'
    b'LoginRes\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x13\n\x0block_region'
    b'\x18\x02 \x01(\t\x12\x13\n\x0bnoti_region\x18\x03 \x01(\t\x12\x11\n\tip_'
    b'region\x18\x04 \x01(\t\x12\x19\n\x11\x61gora_environment\x18\x05 \x01(\t'
    b'\x12\x19\n\x11new_active_region\x18\x06 \x01(\t\x12\x19\n\x11recommend_'
    b'regions\x18\x07 \x03(\t\x12\r\n\x05token\x18\x08 \x01(\t\x12\x0b\n\x03ttl'
    b'\x18\t \x01(\r\x12\x12\n\nserver_url\x18\n \x01(\t\x12\x16\n\x0e\x65mul'
    b'ator_score\x18\x0b \x01(\r\x12$\n\tblacklist\x18\x0c \x01(\x0b\x32\x11.'
    b'BlacklistInfoRes\x12#\n\nqueue_info\x18\r \x01(\x0b\x32\x0f.LoginQueue'
    b'Info\x12\x0e\n\x06tp_url\x18\x0e \x01(\t\x12\x15\n\rapp_server_id\x18'
    b'\x0f \x01(\r\x12\x0f\n\x07\x61no_url\x18\x10 \x01(\t\x12\x0f\n\x07ip_city'
    b'\x18\x11 \x01(\t\x12\x16\n\x0eip_subdivision\x18\x12 \x01(\t*\xa8\x01\n'
    b'\tBanReason\x12\x16\n\x12\x42\x41N_REASON_UNKNOWN\x10\x00\x12\x1b\n\x17'
    b'\x42\x41N_REASON_IN_GAME_AUTO\x10\x01\x12\x15\n\x11\x42\x41N_REASON_'
    b'REFUND\x10\x02\x12\x15\n\x11\x42\x41N_REASON_OTHERS\x10\x03\x12\x16\n'
    b'\x12\x42\x41N_REASON_SKINMOD\x10\x04\x12 \n\x1b\x42\x41N_REASON_IN_GAME'
    b'_AUTO_NEW\x10\xf6\x07\x62\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "FreeFire_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_BANREASON"]._serialized_start = 738
    _globals["_BANREASON"]._serialized_end = 906
    _globals["_LOGINREQ"]._serialized_start = 18
    _globals["_LOGINREQ"]._serialized_end = 117
    _globals["_BLACKLISTINFORES"]._serialized_start = 119
    _globals["_BLACKLISTINFORES"]._serialized_end = 212
    _globals["_LOGINQUEUEINFO"]._serialized_start = 214
    _globals["_LOGINQUEUEINFO"]._serialized_end = 316
    _globals["_LOGINRES"]._serialized_start = 319
    _globals["_LOGINRES"]._serialized_end = 735

LoginReq = _globals["LoginReq"]
LoginRes = _globals["LoginRes"]

MAIN_KEY = base64.b64decode("WWcmdGMlREV1aDYlWmNeOA==")
MAIN_IV  = base64.b64decode("Nm95WkRyMjJFM3ljaGpNJQ==")
RELEASEVERSION = "OB55"
USERAGENT = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
LOGIN_URL = "https://loginbp.ppmainecoonghj.com/"
JWT_CACHE_TTL = 7 * 3600  # 7 hours

_http_client = httpx.Client(
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
    timeout=httpx.Timeout(15.0, connect=5.0),
)

# ==================== CORE FUNCTIONS (importable) ====================

def _pad(data: bytes) -> bytes:
    n = AES.block_size - (len(data) % AES.block_size)
    return data + bytes([n] * n)

def _aes_encrypt(plaintext: bytes) -> bytes:
    return AES.new(MAIN_KEY, AES.MODE_CBC, MAIN_IV).encrypt(_pad(plaintext))

def _try_parse(data: bytes):
    try:
        msg = LoginRes()
        msg.ParseFromString(data)
        if msg.account_id and msg.account_id > 0:
            return json.loads(json_format.MessageToJson(msg))
    except Exception:
        pass
    return None

def _extract_login_res(raw: bytes) -> dict:
    r = _try_parse(raw)
    if r: return r
    idx = 0
    while True:
        idx = raw.find(b"\x08", idx)
        if idx == -1: break
        r = _try_parse(raw[idx:])
        if r: return r
        idx += 1
    jwt_marker = raw.find(b"eyJhbGciOiJIUzI1NiIs")
    if jwt_marker != -1:
        for i in range(jwt_marker - 1, max(jwt_marker - 300, -1), -1):
            if raw[i] == 0x42:
                r = _try_parse(raw[i:])
                if r: return r
                break
    raise Exception(f"Could not parse LoginRes. Raw: {raw[:200]}")

def _get_access_token(uid: str, password: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = (
        f"uid={uid}&password={password}"
        "&response_type=token&client_type=2"
        "&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
        "&client_id=100067"
    )
    hdrs = {
        "User-Agent": USERAGENT, "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip", "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = _http_client.post(url, data=payload, headers=hdrs)
    d = resp.json()
    return d.get("access_token", "0"), d.get("open_id", "0")

def generate_jwt(uid: str, password: str) -> str:
    """
    Main exportable function.
    Returns JWT token string. Raises Exception on failure.
    """
    token_val, open_id = _get_access_token(uid, password)
    if token_val == "0" or open_id == "0":
        raise Exception("Invalid uid/password — no access token")

    body = json.dumps({
        "open_id": open_id,
        "open_id_type": "4",
        "login_token": token_val,
        "orign_platform_type": "4",
    })
    msg_obj = LoginReq()
    json_format.ParseDict(json.loads(body), msg_obj)
    payload = _aes_encrypt(msg_obj.SerializeToString())

    hdrs = {
        "User-Agent": USERAGENT, "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-Ga-Sv": "1789534056", "Authorization": "Bearer",
        "X-Ga": "v1 1", "Releaseversion": RELEASEVERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
        "PlAy_VeR": "1.132.1", "Ob_VeR": RELEASEVERSION,
    }
    resp = _http_client.post(f"{LOGIN_URL}MajorLogin", data=payload, headers=hdrs)
    msg = _extract_login_res(resp.content)
    token = msg.get("token", "")
    if not token or not token.startswith("eyJ"):
        raise Exception(f"No valid JWT in response")
    return token

def get_jwt_cached(uid: str, password: str, group_id: str) -> str:
    """
    Returns cached JWT if valid, else generates new one and saves to
    group_{group_id}_jwt.json. Raises on failure.
    """
    cache_file = f"group_{group_id}_jwt.json"

    # cache check
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            age = time.time() - cached.get("saved_at", 0)
            if age < JWT_CACHE_TTL and cached.get("token", "").startswith("eyJ"):
                return cached["token"]
        except Exception:
            pass

    # generate new
    token = generate_jwt(uid, password)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"token": token, "uid": uid, "saved_at": time.time()}, f, indent=2)
    return token

import os  # needed for get_jwt_cached

# ==================== FLASK API (optional, runs if __main__) ====================

flask_app = Flask(__name__)
CORS(flask_app)

@flask_app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "endpoint": "/api/jwt?uid=UID&password=PASS",
    }), 200

@flask_app.route("/api/jwt", methods=["GET"])
def api_jwt():
    uid = request.args.get("uid", "").strip()
    password = request.args.get("password", "").strip()
    group_id = request.args.get("group_id", "").strip()
    if not uid or not password:
        return jsonify({"status": "error", "error": "uid and password required"}), 400
    try:
        if group_id:
            token = get_jwt_cached(uid, password, group_id)
        else:
            token = generate_jwt(uid, password)
        return jsonify({"status": "success", "token": token, "uid": uid}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=5000, debug=False)