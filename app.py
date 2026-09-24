# api/index.py
from flask import Flask, request, jsonify, make_response
import os, sys, time, threading, json, random, requests, re, codecs, base64, hmac, hashlib, string, secrets
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import urllib3
import concurrent.futures

urllib3.disable_warnings()

# ========== CONFIG ==========
REGION_LANG = {
    "JAWA": "id", "JEPANG": "ja", "MALAYSIA": "ms", "VIETNAM": "vi",
    "ME": "ar", "IND": "hi", "ID": "id", "VN": "vi", "TH": "th",
    "BD": "bn", "PK": "ur", "TW": "zh", "CIS": "ru", "SAC": "es", "BR": "pt"
}
HEX_KEY = bytes.fromhex("32656534343831396539623435393838343531343130363762323831363231383734643064356437616639643866376530306331653534373135623764316533")
AES_KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
AES_IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])
OPT = {'timeout': 8, 'retries': 2, 'backoff': 0.5}
RARITY_SCORE_THRESHOLD = 8

# ========== LOCKED UA (from sc.py) ==========
MSDK_UA   = "GarenaMSDK/4.0.44(25028RN03A ;Android 15;ar;EG;app 1.132.1 2019121229;)"
UNITY_UA  = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
OB_VERSION      = "OB54"
OB_LOGIN_VER    = "OB55"
UNITY_VERSION   = "2018.4.12f1"
UNITY_VERSION_M = "2018.4.11f1"
GA_SV           = "1789535859"

# DataDome cookie — swap with a fresh one if you got it. Placeholder from sc.py.
DATADOME_COOKIE = (
    "datadome=oYpIhVco_RFvLHe_T9KFd5wuY0gcQuNfrlt4rHJY5QOkwv4TGt8gPMK32MbHuBdz"
    "JyfXnXlfzNZT_2tHr2kys8AMYT2~T71QP1S78_7Pdx4JLOXdSrflPT6cOX2vsyJh"
)

# ========== GLOBAL SESSION ==========
_GLOBAL_SESSION = None
_SESSION_LOCK = threading.Lock()

def get_session():
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is None:
        with _SESSION_LOCK:
            if _GLOBAL_SESSION is None:
                s = requests.Session()
                s.verify = False
                s.headers.update({
                    "User-Agent": MSDK_UA,
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                })
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=200, pool_maxsize=200, max_retries=0
                )
                s.mount("https://", adapter)
                s.mount("http://", adapter)
                _GLOBAL_SESSION = s
    return _GLOBAL_SESSION

# ========== IP SPOOF ==========
class FastIPSpoofer:
    _POOL = []
    _IDX = 0
    _LK = threading.Lock()
    @classmethod
    def init(cls, count=5000):
        if not cls._POOL:
            for _ in range(count):
                cls._POOL.append(f"{random.randint(1,254)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}")
    @classmethod
    def get(cls):
        with cls._LK:
            ip = cls._POOL[cls._IDX % len(cls._POOL)]
            cls._IDX += 1
            return ip
FastIPSpoofer.init(5000)

# ========== RETRY ==========
def req(method, url, **kw):
    s = get_session()
    for i in range(OPT['retries'] + 1):
        try:
            kw.setdefault('timeout', OPT['timeout'])
            kw.setdefault('headers', {})
            kw['verify'] = False
            r = s.request(method, url, **kw)
            if r.status_code in (429,500,502,503,504,408) and i < OPT['retries']:
                time.sleep(OPT['backoff'] * (i + 1)); continue
            return r
        except Exception:
            if i < OPT['retries']:
                time.sleep(OPT['backoff'] * (i + 1)); continue
            return None
    return None

# ========== PROTO ==========
def varint(n):
    if n < 0: return b''
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

def pf(fn, v):
    if isinstance(v, dict):
        n = b''.join(pf(k, val) for k, val in v.items())
        return varint((fn << 3) | 2) + varint(len(n)) + n
    if isinstance(v, int):
        return varint((fn << 3) | 0) + varint(v)
    if isinstance(v, (str, bytes)):
        e = v.encode() if isinstance(v, str) else v
        return varint((fn << 3) | 2) + varint(len(e)) + e
    return b''

def build_proto(fields):
    return b''.join(pf(k, v) for k, v in fields.items())

def aes_encrypt_hex(plain_hex):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(bytes.fromhex(plain_hex), AES.block_size)).hex()

# ========== NAME ==========
INVIS = "\u3164"
WRAP = [('꧁','꧂'), ('『','』'), ('【','】'), ('《','》'), ('〈','〉')]
SYM = ['☆','★','✧','✦','✩','✪','✫','♡','♥','❤','❥','❦','ゝ','々']

def exp_sup():
    d = {'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹'}
    return ''.join(d[c] for c in f"{random.randint(1,9999):04d}")

def gen_name(base):
    e = exp_sup()
    r = random.random()
    if r < 0.3:
        l, rr = random.choice(WRAP); return f"{l}{base}{rr}{e}"
    elif r < 0.55:
        return f"{base}{random.choice(SYM)}{e}"
    elif r < 0.8:
        return f"{base}_{e}"
    else:
        tag = f"{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.randint(10,99)}"
        return f"{base}{INVIS}{tag}{e}"

def gen_password(prefix="RYANN"):
    return f"{prefix}_{secrets.token_hex(6).upper()}"

# ========== RARITY ==========
PATTERNS = {
    "R4": (r"(\d)\1{3,}", 5),
    "R3": (r"(\d)\1\1(\d)\2\2", 4),
    "S5": (r"(12345|23456|34567|45678|56789)", 6),
    "S4": (r"(0123|1234|2345|3456|4567|5678|6789|9876|8765|7654|6543|5432|4321|3210)", 5),
    "P6": (r"^(\d)(\d)(\d)\3\2\1$", 7),
    "P4": (r"^(\d)(\d)\2\1$", 5),
    "SPH": (r"(69|420|1337|007)", 6),
    "SPM": (r"(100|200|300|400|500|666|777|888|999)", 4),
    "QD": (r"(1111|2222|3333|4444|5555|6666|7777|8888|9999|0000)", 6),
    "MH": (r"^(\d{2,3})\1$", 5),
    "MM": (r"(\d{2})0\1", 4),
    "GD": (r"1618|0618", 5),
    "ULTRA_R4": (r"(\d)\1{5,}", 10),
    "ULTRA_PAL": (r"^(\d)(\d)(\d)\2\1$", 8),
    "ULTRA_MIRROR": (r"^(\d{3})(\d{3})\1$", 9),
    "ULTRA_SEQ": (r"(012345|123456|234567|345678|456789|987654|876543|765432|654321)", 8),
    "ULTRA_QUAD": (r"(\d{4})\1", 8),
    "ULTRA_BIN": (r"^[01]+$", 7),
    "ULTRA_REP": (r"(\d{2})\1\1", 7),
}
COMP = {k: (re.compile(p), pts) for k, (p, pts) in PATTERNS.items()}

def score_rarity(acc_id):
    if not acc_id or acc_id == "N/A": return 0, []
    score = 0
    found = []
    for k, (pat, pts) in COMP.items():
        if pat.search(acc_id):
            score += pts; found.append(k)

    digits = [int(c) for c in acc_id if c.isdigit()]
    dc = len(digits)

    if dc >= 4 and len(set(digits)) == 1:
        b = min(dc * 2, 12); score += b; found.append(f"UNIFORM(+{b})")

    if dc >= 4:
        diffs = [digits[i+1] - digits[i] for i in range(len(digits)-1)]
        if len(set(diffs)) == 1:
            b = min(abs(diffs[0]) * 2, 10); score += b; found.append(f"ARITH(+{b})")

    if acc_id.isdigit() and len(acc_id) <= 8:
        n = int(acc_id)
        if n < 10**6: score += 8; found.append("LOW_ID(<1M)")
        elif n < 10**7: score += 5; found.append("LOW_ID(<10M)")
        elif n < 10**8: score += 3; found.append("LOW_ID(<100M)")

    if acc_id.isdigit(): score += 2; found.append("CLEAN_DIGIT")
    if len(acc_id) >= 3 and acc_id == acc_id[::-1]: score += 6; found.append("PALINDROME")
    if "888" in acc_id or "999" in acc_id: score += 5; found.append("TRIPLE_888_999")
    if "0000" in acc_id: score += 7; found.append("QUAD_ZUY")

    if dc >= 4:
        rising = all(digits[i] < digits[i+1] for i in range(dc-1))
        sinking = all(digits[i] > digits[i+1] for i in range(dc-1))
        if rising or sinking:
            b = min(dc * 2, 10); score += b; found.append(f"RISE_SINK(+{b})")

    return score, found

def tier_from_score(score):
    if score >= 20: return "LEGENDARY"
    if score >= 16: return "MYTHIC"
    if score >= 12: return "EPIC"
    if score >= RARITY_SCORE_THRESHOLD: return "RARE"
    return "NORMAL"

# ========== GARENA CHAIN ==========
def garena_create(region, name_prefix, password_prefix):
    try:
        password = gen_password(password_prefix)
        region_up = region.upper()
        lang = REGION_LANG.get(region_up, "en")

        # --- 1. REGISTER (MSDK UA + Signature) ---
        reg_payload = json.dumps(
            {"app_id": 100067, "client_type": 2, "password": password, "source": 2},
            separators=(',', ':')
        )
        sig = hmac.new(HEX_KEY, reg_payload.encode(), hashlib.sha256).hexdigest()
        h_reg = {
            "User-Agent": MSDK_UA,
            "Connection": "Keep-Alive",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Authorization": f"Signature {sig}",
            "Content-Type": "application/json; charset=utf-8",
            "Cookie": DATADOME_COOKIE,
            "Host": "100067.connect.garena.com",
            "X-Forwarded-For": FastIPSpoofer.get(),
            "X-Real-IP": FastIPSpoofer.get(),
        }
        r = req('POST', "https://100067.connect.garena.com/api/v2/oauth/guest:register",
                headers=h_reg, data=reg_payload)
        if not r or r.status_code != 200:
            return None
        try:
            j = r.json()
            if j.get("code") != 0 and "data" not in j:
                return None
            uid = j['data']['uid']
        except Exception:
            return None

        # --- 2. TOKEN GRANT (MSDK UA + JSON body) ---
        tok_payload = json.dumps({
            "client_id": 100067,
            "client_secret": HEX_KEY.hex(),
            "client_type": 2,
            "device_id": "02-344afb0e-593c-40b7-92f2-171972f74807",
            "password": password,
            "response_type": "token",
            "uid": uid,
        }, separators=(',', ':'))
        h_tok = {
            "User-Agent": MSDK_UA,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Cookie": DATADOME_COOKIE,
            "Host": "100067.connect.garena.com",
            "X-Forwarded-For": FastIPSpoofer.get(),
            "X-Real-IP": FastIPSpoofer.get(),
        }
        r = req('POST', "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant",
                headers=h_tok, data=tok_payload)
        if not r or r.status_code != 200:
            return None
        try:
            j = r.json()
            access_token = j['data']['access_token']
            open_id = j['data']['open_id']
        except Exception:
            return None

        # --- 3. XOR FIELD ---
        ks = [0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,
              0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30]
        field = codecs.decode(
            ''.join(chr(ord(open_id[i]) ^ ks[i % len(ks)]) for i in range(len(open_id)))
            .encode('unicode_escape').decode('utf-8'), 'unicode_escape'
        ).encode('latin1')

        name = gen_name(name_prefix)
        base_host = "loginbp.common.ggbluefox.com" if region_up in ("ME","TH") else "loginbp.ggpolarbear.com"

        # --- 4. MAJOR REGISTER (MSDK UA + OB54) ---
        proto = build_proto({
            1: name, 2: access_token, 3: open_id, 5: 102000007,
            6: 4, 7: 1, 13: 1, 14: field, 15: lang, 16: 1, 17: 1
        })
        enc_major = bytes.fromhex(aes_encrypt_hex(proto.hex()))
        h_maj = {
            "Content-Type": "application/x-www-form-urlencoded",
            "ReleaseVersion": OB_VERSION,
            "User-Agent": MSDK_UA,
            "X-GA": "v1 1",
            "X-Unity-Version": UNITY_VERSION_M,
            "X-Forwarded-For": FastIPSpoofer.get(),
            "X-Real-IP": FastIPSpoofer.get(),
        }
        req('POST', f"https://{base_host}/MajorRegister", headers=h_maj, data=enc_major)

        # --- 5. MAJOR LOGIN (UnityPlayer UA + OB55) ---
        payload_parts = [
            b'\x1a\x132025-08-30 05:19:21"\tfree fire(\x01:\x081.114.13B2Android OS 9 / API-28 (PI/rel.cjw.20220518.114133)J\x08HandheldR\nATM MobilsZ\x04WIFI`\xb6\nh\xee\x05r\x03300z\x1fARMv7 VFPv3 NEON VMH | 2400 | 2\x80\x01\xc9\x0f\x8a\x01\x0fAdreno (TM) 640\x92\x01\rOpenGL ES 3.2\x9a\x01+Google|dfa4ab4b-9dc4-454e-8065-e70c733fa53f\xa2\x01\x0e105.235.139.91\xaa\x01\x02',
            lang.encode("ascii"),
            b'\xb2\x01 1d8ec0240ede109973f3321b9354b44d\xba\x01\x014\xc2\x01\x08Handheld\xca\x01\x10Asus ASUS_I005DA\xea\x01@afcfbf13334be42036e4f742c80b956344bed760ac91b3aff9b607a610ab4390\xf0\x01\x01\xca\x02\nATM Mobils\xd2\x02\x04WIFI\xca\x03 7428b253defc164018c604a1ebbfebdf\xe0\x03\xa8\x81\x02\xe8\x03\xf6\xe5\x01\xf0\x03\xaf\x13\xf8\x03\x84\x07\x80\x04\xe7\xf0\x01\x88\x04\xa8\x81\x02\x90\x04\xe7\xf0\x01\x98\x04\xa8\x81\x02\xc8\x04\x01\xd2\x04=/data/app/com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg==/lib/arm\xe0\x04\x01\xea\x04_2087f61c19f57f2af4e7feff0b24d9d9|/data/app/com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg==/base.apk\xf0\x04\x03\xf8\x04\x01\x8a\x05\x0232\x9a\x05\n2019118693\xb2\x05\tOpenGLES2\xb8\x05\xff\x7f\xc0\x05\x04\xe0\x05\xf3F\xea\x05\x07android\xf2\x05pKqsHT5ZLWrYljNb5Vqh//yFRlaPHSO9NWSQsVvOmdhEEn7W+VHNUK+Q+fduA3ptNrGB0Ll0LRz3WW0jOwesLj6aiU7sZ40p8BfUE/FI/jzSTwRe2\xf8\x05\xfb\xe4\x06\x88\x06\x01\x90\x06\x01\x9a\x06\x014\xa2\x06\x014\xb2\x06"GQ@O\x00\x0e^\x00D\x06UA\x0ePM\r\x13hZ\x07T\x06\x0cm\\V\x0ejYV;\x0bU5'
        ]
        raw = b''.join(payload_parts)
        raw = raw.replace(b'afcfbf13334be42036e4f742c80b956344bed760ac91b3aff9b607a610ab4390', access_token.encode())
        raw = raw.replace(b'1d8ec0240ede109973f3321b9354b44d', open_id.encode())
        enc_login = bytes.fromhex(aes_encrypt_hex(raw.hex()))
        h_log = {
            "User-Agent": UNITY_UA,
            "Accept-Encoding": "deflate, gzip",
            "X-GA-SV": GA_SV,
            "Authorization": "Bearer",
            "X-GA": "v1 1",
            "ReleaseVersion": OB_LOGIN_VER,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Unity-Version": UNITY_VERSION,
            "X-Forwarded-For": FastIPSpoofer.get(),
            "X-Real-IP": FastIPSpoofer.get(),
        }
        r = req('POST', f"https://{base_host}/MajorLogin", headers=h_log, data=enc_login)

        account_id = "N/A"
        jwt_token = ""
        if r and r.status_code == 200 and len(r.text) > 10:
            idx = r.text.find("eyJ")
            if idx != -1:
                tk = r.text[idx:]
                dot2 = tk.find(".", tk.find(".") + 1)
                if dot2 != -1:
                    tk = tk[:dot2 + 44]
                    try:
                        p = tk.split('.')[1]
                        p += '=' * (4 - len(p) % 4)
                        d = json.loads(base64.urlsafe_b64decode(p))
                        account_id = str(d.get('account_id') or d.get('external_id') or "N/A")
                        jwt_token = tk
                    except Exception:
                        pass

        if account_id == "N/A":
            return None

        # --- 6. REGION BIND ---
        if jwt_token and region_up != "BR":
            try:
                rc = "RU" if region_up == "CIS" else region_up
                pb = build_proto({1: rc})
                enc_rb = aes_encrypt_hex(pb.hex())
                h_rb = {
                    'Content-Type': "application/x-www-form-urlencoded",
                    'Authorization': f"Bearer {jwt_token}",
                    'X-Unity-Version': UNITY_VERSION_M,
                    'X-GA': "v1 1",
                    'ReleaseVersion': OB_VERSION,
                    'User-Agent': MSDK_UA,
                    'X-Forwarded-For': FastIPSpoofer.get(),
                    'X-Real-IP': FastIPSpoofer.get(),
                }
                req('POST', f"https://{base_host}/ChooseRegion", data=bytes.fromhex(enc_rb), headers=h_rb)
            except Exception:
                pass

        return {
            "uid": str(uid),
            "password": password,
            "name": name,
            "region": region_up,
            "account_id": account_id,
            "jwt_token": jwt_token,
            "created_at": datetime.now().isoformat(),
        }
    except Exception:
        return None

# ========== FLASK ==========
app = Flask(__name__)

@app.after_request
def cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,OPTIONS'
    return resp

@app.route('/', methods=['GET', 'OPTIONS'])
def index():
    if request.method == 'OPTIONS':
        return make_response('', 200)
    return jsonify({
        "message": "Free Fire Account Generator API v2",
        "ua_mode": "locked-msdk-4.0.44",
        "endpoint": "/gen?count=5&name=RYANN&password=RYANN&region=JAWA",
        "regions": list(REGION_LANG.keys())
    })

@app.route('/gen', methods=['GET', 'OPTIONS'])
def gen():
    if request.method == 'OPTIONS':
        return make_response('', 200)

    count = request.args.get('count', default=1, type=int)
    name = request.args.get('name', default='RYANN', type=str)
    password = request.args.get('password', default='RYANN', type=str)
    region = request.args.get('region', default='JAWA', type=str).upper()

    if count < 1 or count > 100:
        return jsonify({"error": "count must be 1-100"}), 400
    if not name or not password:
        return jsonify({"error": "name and password required"}), 400
    if region not in REGION_LANG:
        return jsonify({"error": f"invalid region, allowed: {list(REGION_LANG.keys())}"}), 400

    max_workers = min(20, count)
    accounts = []
    attempts = 0
    lock = threading.Lock()
    stop = False

    def worker():
        nonlocal attempts, stop
        if stop: return
        with lock:
            attempts += 1
        acc = garena_create(region, name, password)
        if not acc:
            return
        score, found = score_rarity(acc["account_id"])
        acc["rarity_score"] = score
        acc["rarity"] = tier_from_score(score)
        acc["patterns"] = found[:10]
        with lock:
            if len(accounts) < count:
                accounts.append(acc)
            else:
                stop = True

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(worker) for _ in range(count * 3)]
        t0 = time.time()
        while len(accounts) < count and time.time() - t0 < 25:
            time.sleep(0.1)
        stop = True
        for f in futs:
            f.cancel()

    return jsonify({
        "success": True,
        "total_requested": count,
        "total_created": len(accounts),
        "attempts_made": attempts,
        "region": region,
        "ua_mode": "locked-msdk-4.0.44",
        "accounts": accounts,
    })

app = app

if __name__ == "__main__":
    app.run(debug=False)