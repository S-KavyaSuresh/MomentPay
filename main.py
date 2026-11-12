# """MomentPay backend (FastAPI). Free stack: PayPal Sandbox, Gemini free tier, DummyJSON + FakeStore APIs, SQLite."""
# import os, json, base64, time, secrets, hashlib, sqlite3, uuid, re, asyncio
# from collections import defaultdict
# from contextlib import closing
# import httpx
# from dotenv import load_dotenv
# from fastapi import FastAPI, Depends, Header, HTTPException, Request, BackgroundTasks
# from fastapi.staticfiles import StaticFiles
# from pydantic import BaseModel

# load_dotenv()
# PP_ID, PP_SECRET = os.getenv("PAYPAL_CLIENT_ID", ""), os.getenv("PAYPAL_CLIENT_SECRET", "")
# PP = "https://api-m.sandbox.paypal.com"
# # Contributions are collected straight into the ORGANISER's PayPal account. Set to false to collect into the app's own sandbox business wallet instead.
# COLLECT_TO_ORGANISER = os.getenv("COLLECT_TO_ORGANISER", "true").lower() == "true"
# GKEY, GMODEL = os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# GROQ_KEY, GROQ_MODEL = os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# BASE = os.getenv("BASE_URL", "http://localhost:8000")
# FALLBACK = os.getenv("DEMO_FALLBACK", "true").lower() == "true"
# DB = os.getenv("DB_PATH", "momentpay.db")

# SCHEMA = """
# create table if not exists users(id integer primary key, name text, email text unique, paypal_email text, pw text, token text);
# create table if not exists moments(id integer primary key, organiser_id int, recipient_id int, kind text, occasion text, description text, context text, surprise int, target real, status text default 'draft', message text, recipient_choice text, recipient_spec text);
# create table if not exists members(moment_id int, user_id int);
# create table if not exists contributions(id integer primary key, moment_id int, user_id int, amount real, order_id text);
# create table if not exists purchases(id integer primary key, moment_id int, title text, store text, price real, reasoning text, order_id text, status text);
# create table if not exists payouts(id integer primary key, moment_id int, user_id int, amount real, kind text, batch_id text, status text);
# create table if not exists events(id integer primary key, body text);
# create table if not exists notifs(id integer primary key, user_id int, moment_id int, icon text, title text, body text, ts text default (datetime('now')), seen int default 0);
# create table if not exists chat(id integer primary key, moment_id int, user_id int, kind text, body text, ts text default (datetime('now')));
# """

# def q(sql, a=(), one=False, w=False):
#     with closing(sqlite3.connect(DB)) as c:
#         c.row_factory = sqlite3.Row
#         cur = c.execute(sql, a)
#         if w:
#             c.commit(); return cur.lastrowid
#         r = cur.fetchall()
#         return (r[0] if r else None) if one else r

# with closing(sqlite3.connect(DB)) as _c:
#     _c.executescript(SCHEMA)
#     try: _c.execute("pragma journal_mode=wal")  # readers no longer wait on writers, so polling and saving stop blocking each other
#     except sqlite3.OperationalError: pass
#     for _st in ("alter table moments add column ai_ok int default 0", "alter table purchases add column link text default ''",
#                 "alter table users add column phone text default ''", "alter table users add column city text default ''", "alter table users add column about text default ''"):
#         try: _c.execute(_st)
#         except sqlite3.OperationalError: pass

# app = FastAPI(title="MomentPay")

# # ---------- auth ----------
# def h(pw): return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"momentpay-demo", 100_000).hex()
# EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# def me(authorization: str = Header("")):
#     u = q("select * from users where token=?", (authorization,), one=True) if authorization else None
#     if not u: raise HTTPException(401, "Please log in")
#     return u

# class Auth(BaseModel):
#     email: str; password: str; name: str = ""; paypal_email: str = ""

# @app.post("/api/register")
# def register(b: Auth):
#     if not (b.name and b.email and b.paypal_email and b.password): raise HTTPException(400, "Fill in every field")
#     if not (EMAIL_RE.fullmatch(b.email) and EMAIL_RE.fullmatch(b.paypal_email)): raise HTTPException(400, "Enter valid email addresses")
#     if q("select 1 from users where email=?", (b.email.lower(),), one=True): raise HTTPException(400, "Email already registered")
#     t = secrets.token_hex(16)
#     q("insert into users(name,email,paypal_email,pw,token) values(?,?,?,?,?)", (b.name, b.email.lower(), b.paypal_email, h(b.password), t), w=True)
#     return {"token": t}

# @app.post("/api/login")
# def login(b: Auth):
#     u = q("select * from users where email=? and pw=?", (b.email.lower(), h(b.password)), one=True)
#     if not u: raise HTTPException(401, "Wrong email or password")
#     return {"token": u["token"]}

# @app.get("/api/me")
# def whoami(u=Depends(me)): return {"id": u["id"], "name": u["name"], "email": u["email"]}

# @app.get("/api/users")
# def users(q_: str = "", u=Depends(me)):
#     t = q_.strip().lower()
#     if len(t) < 2: return []  # no browsing the user list: search by name, or exact email
#     rows = q("select id,name,email from users where id!=? and (lower(name) like ? or email=?) limit 8", (u["id"], f"%{t}%", t))
#     return [{"id": r["id"], "name": r["name"], "email": r["email"][0] + "***" + r["email"][r["email"].index("@"):]} for r in rows]

# @app.get("/api/config")
# def config(): return {"client_id": PP_ID, "ai": bool(GKEY or GROQ_KEY), "search": "google" if os.getenv("SERPAPI_KEY") else "demo", "collect_org": COLLECT_TO_ORGANISER}

# # ---------- profile ----------
# class Profile(BaseModel):
#     name: str; email: str; paypal_email: str; phone: str = ""; city: str = ""; about: str = ""

# def _clean_profile(b):
#     name, email, pe = b.name.strip(), b.email.strip().lower(), b.paypal_email.strip()
#     phone, city, about = b.phone.strip(), b.city.strip(), b.about.strip()
#     if not (2 <= len(name) <= 60) or not re.search(r"[^\W\d_]", name) or re.search(r"[<>]", name): raise HTTPException(400, "Enter your real name (2 to 60 characters, with letters)")
#     if not EMAIL_RE.fullmatch(email): raise HTTPException(400, "Enter a valid login email")
#     if not EMAIL_RE.fullmatch(pe): raise HTTPException(400, "Enter a valid PayPal email")
#     if phone and not (re.fullmatch(r"\+?[0-9 ()\-.]{7,20}", phone) and 7 <= len(re.sub(r"\D", "", phone)) <= 15): raise HTTPException(400, "Enter a valid phone number, for example +91 98765 43210")
#     if len(city) > 60: raise HTTPException(400, "City is too long (60 characters at most)")
#     if len(about) > 280: raise HTTPException(400, "The about line is too long (280 characters at most)")
#     return name, email, pe, phone, city, about

# @app.get("/api/profile")
# def get_profile(u=Depends(me)):
#     return {k: u[k] or "" for k in ("name", "email", "paypal_email", "phone", "city", "about")}

# @app.put("/api/profile")
# def put_profile(b: Profile, u=Depends(me)):
#     name, email, pe, phone, city, about = _clean_profile(b)
#     if q("select 1 from users where email=? and id!=?", (email, u["id"]), one=True): raise HTTPException(400, "That email already belongs to another account")
#     q("update users set name=?, email=?, paypal_email=?, phone=?, city=?, about=? where id=?", (name, email, pe, phone, city, about, u["id"]), w=True)
#     return {"ok": True}

# # ---------- helpers ----------
# def split(total_cents, weights):
#     """Proportional split in cents using largest remainder, so shares always add up exactly."""
#     s = sum(weights.values()); raw = {k: total_cents * w / s for k, w in weights.items()}
#     base = {k: int(v) for k, v in raw.items()}
#     for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[: total_cents - sum(base.values())]: base[k] += 1
#     return base

# def totals(mid):
#     cs = q("select user_id, sum(amount) a from contributions where moment_id=? group by user_id", (mid,))
#     col = round(sum(c["a"] for c in cs), 2)
#     spent = round(sum(r["price"] for r in q("select price from purchases where moment_id=?", (mid,))), 2)
#     out = round(sum(r["amount"] for r in q("select amount from payouts where moment_id=?", (mid,))), 2)
#     return cs, col, spent, round(col - spent - out, 2)

# def access(mid, u):
#     m = q("select * from moments where id=?", (mid,), one=True)
#     if not m: raise HTTPException(404, "Moment not found")
#     org = m["organiser_id"] == u["id"]
#     mem = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
#     rec = m["recipient_id"] == u["id"] and not m["surprise"] and m["status"] != "draft"
#     if mem and not org and m["status"] == "draft": raise HTTPException(403, "The organiser has not opened this group yet. You will be notified when it is ready.")
#     if not (org or (mem and m["status"] != "draft") or rec): raise HTTPException(403, "No access to this moment")
#     return m, org, rec

# def organiser_only(mid, u, statuses):
#     m, org, _ = access(mid, u)
#     if not org: raise HTTPException(403, "Only the organiser can do this")
#     if m["status"] not in statuses: raise HTTPException(400, f"Not possible while status is '{m['status']}'")
#     return m

# # ---------- PayPal (sandbox) ----------
# _tok = {"v": None, "exp": 0}
# async def pp(method, path, body=None):
#     if not PP_ID: raise HTTPException(500, "PayPal keys missing in .env")
#     try:
#         async with httpx.AsyncClient(timeout=30) as c:
#             if time.time() > _tok["exp"]:
#                 r = await c.post(PP + "/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=(PP_ID, PP_SECRET))
#                 if r.status_code != 200: raise HTTPException(502, "PayPal authentication failed - check your keys")
#                 _tok.update(v=r.json()["access_token"], exp=time.time() + r.json()["expires_in"] - 60)
#             r = await c.request(method, PP + path, json=({} if body is None and method == "POST" else body), headers={"Authorization": "Bearer " + _tok["v"], "Content-Type": "application/json"})
#     except httpx.HTTPError: raise HTTPException(502, "Could not reach PayPal. Check your internet connection.")
#     try: j = r.json()
#     except Exception: j = {}
#     if r.status_code >= 300:
#         iss = "; ".join(f"{d.get('issue', '')} {d.get('description', '')}".strip() for d in (j.get("details") or []) if isinstance(d, dict))
#         print(f"[PayPal] {method} {path} -> {r.status_code}: {r.text[:600]}")
#         raise HTTPException(502, "PayPal: " + (str(j.get("message") or j.get("name") or r.text) + (" - " + iss if iss else ""))[:300])
#     return j

# async def payouts(mid, items, kind):
#     """items: [(user_id, paypal_email, amount)] -> records payouts. Falls back to simulation if Payouts isn't enabled."""
#     body = {"sender_batch_header": {"sender_batch_id": f"mp{mid}-{uuid.uuid4().hex[:10]}", "email_subject": "You received money via MomentPay"},
#             "items": [{"recipient_type": "EMAIL", "receiver": e, "amount": {"value": f"{a:.2f}", "currency": "USD"}, "sender_item_id": f"{kind}-{i}"} for i, (_, e, a) in enumerate(items)]}
#     try:
#         bid, st = (await pp("POST", "/v1/payments/payouts", body))["batch_header"]["payout_batch_id"], "sent"
#     except HTTPException:
#         if not FALLBACK: raise
#         bid, st = "SIM-" + uuid.uuid4().hex[:8], "simulated"
#     for uid, _, a in items: q("insert into payouts(moment_id,user_id,amount,kind,batch_id,status) values(?,?,?,?,?,?)", (mid, uid, a, kind, bid, st), w=True)

# class Contrib(BaseModel):
#     moment_id: int; amount: float = 0; order_id: str = ""

# @app.post("/api/paypal/create-order")
# async def create_order(b: Contrib, u=Depends(me)):
#     m, _, rec = access(b.moment_id, u)
#     if m["recipient_id"] == u["id"]: raise HTTPException(403, "This moment is for you, so you can't contribute to it.")
#     if m["status"] != "active": raise HTTPException(400, "This fund is not open for contributions")
#     if b.amount <= 0: raise HTTPException(400, "Enter an amount above zero")
#     org = q("select paypal_email from users where id=?", (m["organiser_id"],), one=True)
#     unit = {"reference_id": f"moment-{m['id']}", "description": m["occasion"][:120], "amount": {"currency_code": "USD", "value": f"{b.amount:.2f}"}}
#     # PayPal refuses to let an account pay itself, so the organiser's own contribution skips the payee override and lands as a normal capture in the app's own sandbox business wallet instead.
#     if COLLECT_TO_ORGANISER and m["organiser_id"] != u["id"]: unit["payee"] = {"email_address": org["paypal_email"]}
#     try: o = await pp("POST", "/v2/checkout/orders", {"intent": "CAPTURE", "purchase_units": [unit]})
#     except HTTPException as e:
#         if "payee" in str(e.detail).lower(): raise HTTPException(400, "PayPal cannot pay the organiser's PayPal email. It must be a sandbox Business account (or set COLLECT_TO_ORGANISER=false).")
#         raise
#     return {"id": o["id"]}

# @app.post("/api/paypal/capture-order")
# async def capture(b: Contrib, bg: BackgroundTasks, u=Depends(me)):
#     m, _, _ = access(b.moment_id, u)
#     if m["recipient_id"] == u["id"]: raise HTTPException(403, "This moment is for you, so you can't contribute to it.")
#     org = q("select paypal_email from users where id=?", (m["organiser_id"],), one=True)
#     if q("select 1 from contributions where order_id=?", (b.order_id,), one=True): return {"ok": True, "amount": 0, "to_organiser": True}
#     r = await pp("POST", f"/v2/checkout/orders/{b.order_id}/capture")  # money only moves HERE, not when the buyer approves
#     if r.get("status") != "COMPLETED": raise HTTPException(400, "PayPal did not complete the payment, so nothing was charged")
#     amt = float(r["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"])
#     to_org = (r["purchase_units"][0].get("payee") or {}).get("email_address", "").lower() == org["paypal_email"].lower()
#     q("insert into contributions(moment_id,user_id,amount,order_id) values(?,?,?,?)", (b.moment_id, u["id"], amt, b.order_id), w=True)
#     await celebrate(b.moment_id, u, amt, to_org, bg)
#     return {"ok": True, "amount": amt, "to_organiser": to_org}

# @app.post("/api/paypal/webhook")
# async def webhook(r: Request):
#     q("insert into events(body) values(?)", ((await r.body()).decode()[:4000],), w=True)
#     return {"ok": True}

# # ---------- AI (Gemini free tier, with graceful fallbacks) ----------
# AI_ERR = {"ok": False, "msg": ""}
# _dead = {}  # model/provider -> (retry_after, message): a retired model or a rate limit is skipped for a while instead of costing a round trip on every call
# async def ai(prompt, as_json=False):
#     """Gemini first, then Groq (both free tiers). Failures are recorded in AI_ERR so the UI can say why, never silent."""
#     AI_ERR.update(ok=False, msg="")
#     def parse(t):
#         t = t.strip()
#         if not as_json: return t
#         v = json.loads(re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip())
#         if isinstance(v, dict) and len(v) == 1 and isinstance(next(iter(v.values())), list): v = next(iter(v.values()))
#         return v
#     def burn(key, code, msg):
#         if code != 200: _dead[key] = (time.time() + (900 if code in (400, 401, 403, 404) else 30), msg)
#     async with httpx.AsyncClient(timeout=25) as c:
#         if GKEY:
#             for model in dict.fromkeys([GMODEL, "gemini-flash-latest", "gemini-flash-lite-latest"]):
#                 d = _dead.get(model)
#                 if d and d[0] > time.time(): AI_ERR["msg"] = d[1]; continue
#                 j, code = {}, 0
#                 try:
#                     r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": GKEY},
#                                      json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"} if as_json else {}})
#                     code, j = r.status_code, r.json()
#                     if code != 200: raise ValueError(f"HTTP {code} {str((j.get('error') or {}).get('message', r.text))[:160]}")
#                     v = parse("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))); AI_ERR["ok"] = True; return v
#                 except Exception as e:
#                     AI_ERR["msg"] = f"Gemini ({model}): {(j.get('error') or {}).get('message') or repr(e)}"[:220]; burn(model, code, AI_ERR["msg"])
#         if GROQ_KEY:
#             d = _dead.get("groq")
#             if d and d[0] > time.time(): AI_ERR["msg"] = d[1]
#             else:
#                 j, code = {}, 0
#                 try:
#                     r = await c.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + GROQ_KEY},
#                                      json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], **({"response_format": {"type": "json_object"}} if as_json else {})})
#                     code, j = r.status_code, r.json(); v = parse(j["choices"][0]["message"]["content"]); AI_ERR["ok"] = True; return v
#                 except Exception as e:
#                     AI_ERR["msg"] = f"Groq: {(j.get('error') or {}).get('message') or repr(e)}"[:220]; burn("groq", code, AI_ERR["msg"])
#     if not (GKEY or GROQ_KEY): AI_ERR["msg"] = "No AI key found. Add GEMINI_API_KEY or GROQ_API_KEY to .env"
#     return None

# TONES = {"warm": "warm and affectionate", "playful": "playful and witty", "heartfelt": "deeply heartfelt and sincere", "urgent": "urgent yet calm and caring"}
# async def make_message(b, org, rec, sur, mid, same_person=False):
#     link, key = f"{BASE}/#m{mid}", getattr(b, "tone", "warm")
#     key = key if key in TONES else "warm"
#     tone_text = TONES[key] if b.kind != "emergency" else "calm, caring and supportive. This is an EMERGENCY fund: never celebratory, never playful, no party emoji, speak like someone steady helping a friend through a hard moment"
#     role_rule = (f"The organiser and recipient are the SAME PERSON ({rec}). Write in the organiser's first-person voice: they are asking their community for help for themselves. Never describe {rec} as a separate third person, and never say '{rec} is going through...'" if same_person else f"The organiser is {org}; the recipient/beneficiary is {rec}. Make it unmistakable that support is for {rec}, not for the contributors.")
#     t = await ai(f"""You write fundraising messages people genuinely want to read, for a group chat. Tone: {tone_text}.
# Rules: 70-110 words, plain text, at most 2 emoji, short paragraphs. Compose a brand-new message in your own words. {role_rule} Open with a specific detail from the facts, not a generic greeting. {'For an emergency, focus on the affected recipient/family and practical support; do not console contributors or imply that they are suffering.' if b.kind == 'emergency' else ''} {'This is a secret surprise; do not reveal it to the recipient.' if sur else ''}
# Facts: kind={b.kind}; organiser={org}; recipient={rec}; occasion={b.occasion}; details={b.description}; who is who={b.context}; goal=${b.target:.0f}.
# Say plainly that any amount is welcome and nobody is expected to give a fixed share. Finish with exactly this link: {link}""")
#     if t: return t
#     if b.kind == "emergency":
#         opening = (f"I'm raising this fund for myself because {b.description.strip()}" if same_person and b.description.strip() else (f"I'm asking for support for myself during {b.occasion}." if same_person else f"{rec} and their family are facing a difficult situation: {b.description.strip() or b.occasion}."))
#         return f"{opening} We are gathering ${b.target:.0f} to help with immediate needs. Any amount is welcome; there are no fixed shares and no pressure to give. Thank you for standing with us.\n\n{link}"
#     op = {"warm": f"Something lovely is happening for {rec}, and I'd love for you to be part of it.", "playful": f"Breaking news: {rec} has a big one coming up ({b.occasion}) and we are not letting it pass quietly.",
#           "heartfelt": f"{rec} has always shown up for us. Now it is our turn to show up.", "urgent": f"{rec} needs us right now, and this is a way we can help."}[key]
#     return f"{op}\n\nWe are pooling together for {b.occasion}. Our goal is ${b.target:.0f}, but give whatever feels right, there are no fixed shares and every amount truly helps.{' Shh, it is a surprise!' if sur else ''}\n\n{link}"

# # ---------- moments ----------
# class NewMoment(BaseModel):
#     recipient_id: int; occasion: str; target: float; kind: str = "occasion"; description: str = ""; context: str = ""
#     surprise: bool = False; member_ids: list[int] = []; tone: str = "warm"

# @app.post("/api/moments")
# async def new_moment(b: NewMoment, u=Depends(me)):
#     r = q("select * from users where id=?", (b.recipient_id,), one=True)
#     if not r: raise HTTPException(404, "Recipient not found")
#     if b.target <= 0 or not b.occasion.strip(): raise HTTPException(400, "Add an occasion and a target above zero")
#     sur = int(b.surprise and r["id"] != u["id"])
#     if sur and r["id"] in b.member_ids: raise HTTPException(400, "It's a surprise, so the recipient can't be in the group")
#     mid = q("insert into moments(organiser_id,recipient_id,kind,occasion,description,context,surprise,target) values(?,?,?,?,?,?,?,?)",
#             (u["id"], r["id"], b.kind, b.occasion, b.description, b.context, sur, b.target), w=True)
#     ids = set(b.member_ids) - {u["id"]} - ({r["id"]} if sur else set())
#     for uid in ids:
#         q("insert into members values(?,?)", (mid, uid), w=True)
#     if b.kind == "emergency":
#         notify([u["id"]], "You created an emergency fund", mid, "🤍")
#     else:
#         notify([u["id"]], "You created a new moment", mid, "✨")
#     notify(list(ids), f"{u['name']} created a new moment and added you as a contributor. You can join in once the group opens.", mid, "🤝")
#     msg = await make_message(b, u["name"], r["name"], sur, mid, u["id"] == r["id"]); ok = AI_ERR["ok"]
#     q("update moments set message=?, ai_ok=? where id=?", (msg, int(ok), mid), w=True)
#     return {"id": mid, "ai": ok, "err": AI_ERR["msg"]}

# @app.get("/api/moments")
# def my_moments(u=Depends(me)):
#     rows = q("""select distinct m.* from moments m left join members x on x.moment_id=m.id
#         where m.organiser_id=? or (x.user_id=? and m.status!='draft') or (m.recipient_id=? and m.surprise=0 and m.status!='draft') order by m.id desc""", (u["id"],) * 3)
#     return [{"id": m["id"], "occasion": m["occasion"], "kind": m["kind"], "status": m["status"], "target": m["target"], "collected": totals(m["id"])[1], "last": last_msg(m["id"]),
#              "role": "Organiser" if m["organiser_id"] == u["id"] else "Recipient" if m["recipient_id"] == u["id"] else "Contributor"} for m in rows]

# @app.get("/api/moments/{mid}")
# def get_moment(mid: int, u=Depends(me)):
#     m, org, rec = access(mid, u)
#     cs, col, spent, left = totals(mid)
#     names = defaultdict(lambda: "Deleted user", {r["id"]: r["name"] for r in q("select id,name from users")})
#     d = dict(m)
#     d.update(collected=col, spent=spent, leftover=left, is_organiser=org, is_recipient=m["recipient_id"] == u["id"], is_member=q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None,
#              crew=[r["name"] for r in q("select u.name from members x join users u on u.id=x.user_id where x.moment_id=?", (mid,))],
#              organiser_name=names[m["organiser_id"]], recipient_name=names[m["recipient_id"]],
#              contributions=[{"name": names[c["user_id"]], "amount": c["a"], "share": round(c["a"] / col * 100, 1)} for c in cs],
#              purchases=[dict(r) for r in q("select title,store,price,reasoning,status,link from purchases where moment_id=?", (mid,))],
#              payouts=[{"name": names[r["user_id"]], "amount": r["amount"], "kind": r["kind"], "status": r["status"]} for r in q("select * from payouts where moment_id=?", (mid,))],
#              preview=[{"name": names[k], "amount": v / 100} for k, v in split(round(left * 100), {c["user_id"]: c["a"] for c in cs}).items()] if left > 0 and cs else [])
#     return d

# class Msg(BaseModel): message: str

# @app.put("/api/moments/{mid}/message")
# def set_message(mid: int, b: Msg, u=Depends(me)):
#     organiser_only(mid, u, ["draft", "active"]); q("update moments set message=? where id=?", (b.message, mid), w=True); return {"ok": True}

# @app.post("/api/moments/{mid}/send")
# async def send(mid: int, bg: BackgroundTasks, u=Depends(me)):
#     organiser_only(mid, u, ["draft"]); q("update moments set status='active' where id=?", (mid,), w=True); launch(mid, u); bg.add_task(launch_ai, mid); return {"ok": True}

# @app.post("/api/moments/{mid}/close")
# def close(mid: int, u=Depends(me)):
#     organiser_only(mid, u, ["active"])
#     if totals(mid)[1] <= 0: raise HTTPException(400, "No contributions yet")
#     say(mid, f"🔒|The pool is sealed at ${totals(mid)[1]:.2f}|Contributions are closed while the organiser picks the perfect next step.", "pay", u["id"])
#     q("update moments set status='funded' where id=?", (mid,), w=True); return {"ok": True}

# def _no_emergency_extras(m):
#     if m["kind"] == "emergency": raise HTTPException(400, "Emergency funds keep it simple: send the money or return what's left.")

# @app.post("/api/moments/{mid}/ask")
# def ask_recipient(mid: int, u=Depends(me)):
#     m = organiser_only(mid, u, ["funded"])
#     _no_emergency_extras(m)
#     if m["surprise"]: raise HTTPException(400, "Surprise mode: the recipient cannot be asked")
#     say(mid, "💌|A question is on its way|The recipient is choosing between money and something special.", "pay", u["id"], skip={m["recipient_id"]})
#     notify([m["recipient_id"]], "Your friends raised money for you. Would you like it as money or a gift?", mid, "💌")
#     q("update moments set status='asking' where id=?", (mid,), w=True); return {"ok": True}

# class Answer(BaseModel): choice: str; spec: str = ""

# @app.post("/api/moments/{mid}/answer")
# def answer(mid: int, b: Answer, u=Depends(me)):
#     m, _, rec = access(mid, u)
#     if not rec or m["status"] != "asking": raise HTTPException(403, "Nothing to answer right now")
#     if b.choice not in ("money", "gift") or (b.choice == "gift" and not b.spec.strip()): raise HTTPException(400, "Say what you would like")
#     say(mid, "🪄|The recipient has answered|" + ("They would love the money." if b.choice == "money" else "They'd love: " + b.spec[:80]), "pay", u["id"])
#     q("update moments set status='answered', recipient_choice=?, recipient_spec=? where id=?", (b.choice, b.spec, mid), w=True); return {"ok": True}

# @app.post("/api/moments/{mid}/payout")
# async def payout_direct(mid: int, u=Depends(me)):
#     m = organiser_only(mid, u, ["funded", "asking", "answered"])
#     left = totals(mid)[3]
#     if left <= 0: raise HTTPException(400, "Nothing left to send")
#     r = q("select * from users where id=?", (m["recipient_id"],), one=True)
#     await payouts(mid, [(r["id"], r["paypal_email"], left)], "recipient")
#     say(mid, f"🎁|${left:.2f} is on its way to {r['name']}|{pay_line(m['kind'])}", "pay", u["id"], skip={r["id"]})
#     if not m["surprise"]: notify([r["id"]], f"${left:.2f} just landed from your friends 🎁", mid, "🎁")
#     q("update moments set status='done' where id=?", (mid,), w=True); return {"ok": True}

# # ---------- AI product agent (free catalogs: DummyJSON + FakeStore) ----------
# class Spec(BaseModel): spec: str; budget: float = 0

# from urllib.parse import quote
# SERP = os.getenv("SERPAPI_KEY", "")
# _cats = {}

# async def _get(c, url, **kw):
#     try: return (await c.get(url, **kw)).json()
#     except Exception: return None

# async def _categories(c):
#     if not _cats.get("d"):
#         d, f = await asyncio.gather(_get(c, "https://dummyjson.com/products/category-list"), _get(c, "https://fakestoreapi.com/products/categories"))
#         _cats.update(d=d if isinstance(d, list) else [], f=f if isinstance(f, list) else [])
#     return _cats

# def _rate(p):  # ratings backed by many reviews count for more
#     n = p.get("reviews", 0)
#     return (p["rating"] * n + 4.0 * 15) / (n + 15) if n else p["rating"]

# async def find_products(spec, budget):
#     """Real Google Shopping results when SERPAPI_KEY is set, otherwise free demo catalogs matched by AI-chosen categories."""
#     out, seen, src, note = [], set(), "demo", ""
#     def add(**p):
#         if (p["store"], p["title"]) not in seen and p["price"] > 0: seen.add((p["store"], p["title"])); out.append({"reviews": 0, "link": "", "delivery": "", **p})
#     async with httpx.AsyncClient(timeout=12) as c:
#         cats = await _categories(c)
#         plan = await ai("A friend group wants to buy: " + json.dumps(spec) + f" (budget ${budget:.0f}, US shoppers). Return a JSON object with keys: query (the best Google Shopping search query), alts (list of up to 2 alternative queries), "
#                         f"dummy_categories (up to 2 slugs chosen only from {cats['d']}), fake_categories (up to 1 chosen only from {cats['f']}).", True)
#         plan = plan if isinstance(plan, dict) else {}
#         qs = [str(plan.get("query") or spec)] + [str(a) for a in (plan.get("alts") or [])][:2]
#         if SERP:
#             rs = await asyncio.gather(*[_get(c, "https://serpapi.com/search.json", params={"engine": "google_shopping", "q": qy, "api_key": SERP, "gl": "us", "hl": "en", "num": 20}) for qy in qs[:2]])
#             for r in rs:
#                 if not isinstance(r, dict): note = note or "Google Shopping search failed"; continue
#                 if r.get("error"): note = "Google Shopping search failed: " + str(r["error"])[:120]; continue
#                 for p in r.get("shopping_results", []):
#                     try:
#                         pr = p.get("extracted_price") or 0; old = p.get("extracted_old_price") or pr
#                         add(store=p.get("source", "Online store"), title=p.get("title", ""), price=pr, list_price=old, discount=round((1 - pr / old) * 100) if old > pr else 0,
#                             rating=p.get("rating") or 0, reviews=p.get("reviews") or 0, image=p.get("thumbnail", ""), link=p.get("product_link") or p.get("link", ""), delivery=p.get("delivery", ""))
#                     except Exception: pass
#             if out: src, note = "google", ""
#         if not out:
#             def add_d(p):
#                 d = p.get("discountPercentage", 0)
#                 add(store="DummyJSON Store", title=p["title"], list_price=p["price"], discount=round(d), price=round(p["price"] * (1 - d / 100), 2), rating=p.get("rating", 0), reviews=len(p.get("reviews", [])), image=p.get("thumbnail", ""))
#             kws = list(dict.fromkeys(qs + [w for w in spec.split() if len(w) > 3]))[:5]
#             jobs = [_get(c, "https://dummyjson.com/products/search", params={"q": k, "limit": 10}) for k in kws]
#             jobs += [_get(c, f"https://dummyjson.com/products/category/{cat}", params={"limit": 12}) for cat in (plan.get("dummy_categories") or [])[:2] if cat in cats["d"]]
#             fjobs = [_get(c, "https://fakestoreapi.com/products/category/" + quote(cat)) for cat in (plan.get("fake_categories") or [])[:1] if cat in cats["f"]]
#             res = await asyncio.gather(*jobs, *fjobs)
#             for r in res[:len(jobs)]:
#                 for p in (r.get("products", []) if isinstance(r, dict) else []):
#                     try: add_d(p)
#                     except Exception: pass
#             for r in res[len(jobs):]:
#                 for p in (r if isinstance(r, list) else []):
#                     try: add(store="FakeStore", title=p["title"], list_price=p["price"], discount=0, price=p["price"], rating=p["rating"]["rate"], reviews=p["rating"]["count"], image=p["image"])
#                     except Exception: pass
#             note = note or "Showing free demo catalogs. Add a free SERPAPI_KEY to .env for live Google Shopping results."
#     return out, src, note

# @app.post("/api/moments/{mid}/search")
# async def search(mid: int, b: Spec, u=Depends(me)):
#     m = organiser_only(mid, u, ["funded", "asking", "answered"])
#     _no_emergency_extras(m)
#     left = totals(mid)[3]
#     if left <= 0: raise HTTPException(400, "The pool is empty, so there is nothing left to spend.")
#     if not b.spec.strip(): raise HTTPException(400, "Tell Pip what you would like to buy")
#     budget = min(b.budget, left) if b.budget > 0 else left
#     cands, src, note = await find_products(b.spec, budget)
#     base = {"budget": budget, "source": src, "note": note, "candidates": [], "pick": 0, "reasoning": "", "over": []}
#     if not cands: return {**base, "note": (note + " " if note else "") + "Nothing matched that. Try different words."}
#     inb = [p for p in cands if p["price"] <= budget]
#     if not inb:
#         base["over"] = sorted(cands, key=lambda p: p["price"])[:3]
#         return {**base, "note": f"There are matches, but the cheapest starts at ${base['over'][0]['price']:.2f}, above your ${budget:.2f} budget."}
#     for p in inb: p["pre"] = 0.6 * _rate(p) / 5 + 0.4 * (1 - p["price"] / budget)
#     inb = sorted(inb, key=lambda p: -p["pre"])[:10]
#     brief = [{"i": i, "store": p["store"], "title": p["title"], "price": p["price"], "discount_pct": p["discount"], "rating": p["rating"], "reviews": p["reviews"]} for i, p in enumerate(inb)]
#     r = await ai("Wish: " + json.dumps(b.spec) + f". Budget ${budget:.2f}. Options: " + json.dumps(brief) + ". Rate each option's RELEVANCE to the wish from 0 (unrelated) to 10 (exactly what was asked). "
#                  "Then choose the single best overall: relevance first, then rating (trust ratings with many reviews), discount, and sensible use of the budget. "
#                  'Return a JSON object {"relevance": [one integer per option, in order], "i": index of the best option, "reasoning": "two sentences citing real numbers and the store"}.', True)
#     try:
#         rel = [int(x) for x in r["relevance"]]; assert len(rel) == len(inb)
#     except Exception:
#         rel = [6 if any(w.lower()[:5] in p["title"].lower() for w in b.spec.split() if len(w) > 3) else 2 for p in inb]
#     for p, x in zip(inb, rel): p["rel"] = x; p["score"] = round(0.45 * x / 10 + 0.3 * _rate(p) / 5 + 0.15 * (1 - p["price"] / budget) + 0.1 * min(p["discount"], 50) / 50, 3)
#     good = [p for p in inb if p["rel"] >= 4]
#     ranked = sorted(good or inb, key=lambda p: -p["score"])[:6 if good else 3]
#     if not good:
#         for p in ranked: p["weak"] = True
#         note = "Nothing here is a close match for that. These are the nearest items" + (". Try different words." if src == "google" else ", because the free demo catalogs are small. A SERPAPI_KEY gives real store results.")
#     pick, why = 0, ""
#     try:
#         ch = inb[int(r["i"])]
#         if ch in ranked: pick, why = ranked.index(ch), str(r["reasoning"])
#     except Exception: pass
#     if not why: t = ranked[0]; why = f"Top pick: {t['title']} from {t['store']}, rated {t['rating']}/5 at ${t['price']:.2f}, ${budget - t['price']:.2f} under budget."
#     return {**base, "candidates": ranked, "pick": pick, "reasoning": why, "note": note}

# class Buy(BaseModel): title: str; store: str; price: float; reasoning: str = ""; link: str = ""

# @app.post("/api/moments/{mid}/buy")
# async def buy(mid: int, b: Buy, u=Depends(me)):
#     m = organiser_only(mid, u, ["funded", "asking", "answered"])
#     _no_emergency_extras(m)
#     if b.price <= 0 or b.price > totals(mid)[3] + 0.001: raise HTTPException(400, "Price exceeds the funds left")
#     try:
#         oid, st = (await pp("POST", "/v2/checkout/orders", {"intent": "CAPTURE", "purchase_units": [{"reference_id": f"purchase-{mid}", "description": b.title[:120], "amount": {"currency_code": "USD", "value": f"{b.price:.2f}"}}]}))["id"], "order created"
#     except HTTPException:
#         if not FALLBACK: raise
#         oid, st = "SIM-" + uuid.uuid4().hex[:8], "simulated"
#     q("insert into purchases(moment_id,title,store,price,reasoning,order_id,status,link) values(?,?,?,?,?,?,?,?)", (mid, b.title, b.store, b.price, b.reasoning, oid, st, b.link), w=True)
#     say(mid, f"🛍️|Bought: {b.title[:60]} (${b.price:.2f})|{pay_line(m['kind'])}", "pay", u["id"], skip={m["recipient_id"]})
#     if not m["surprise"]: notify([m["recipient_id"]], f"A gift is on its way: {b.title[:60]}", mid, "🛍️")
#     return {"ok": True}

# @app.post("/api/moments/{mid}/refund")
# async def refund(mid: int, u=Depends(me)):
#     organiser_only(mid, u, ["funded", "asking", "answered"])
#     cs, _, _, left = totals(mid)
#     if left <= 0: raise HTTPException(400, "Nothing left to return")
#     shares = split(round(left * 100), {c["user_id"]: c["a"] for c in cs})
#     em = {r["id"]: r["paypal_email"] for r in q("select id,paypal_email from users")}
#     await payouts(mid, [(k, em[k], v / 100) for k, v in shares.items() if v > 0], "refund")
#     say(mid, f"🌿|${left:.2f} returned to contributors|Shared in proportion to what each person gave. Every cent found its way home.", "pay", u["id"])
#     q("update moments set status='done' where id=?", (mid,), w=True); return {"ok": True}

# # ---------- group chat + Pip (AI assistant) ----------
# import random, re
# from types import SimpleNamespace
# PAY = ["Your value has safely changed hands.", "The digital currents have carried your treasure through.", "A successful handshake between balances.", "Kindness, delivered at the speed of light.", "Another thread woven into the tapestry.", "The coins found their way home."]
# PAY_CALM = ["Your contribution is safely in.", "Steady hands, steady support. It has arrived.", "One more person standing behind them.", "Quietly, surely, it found its way there.", "Support delivered, no fuss, no delay."]
# def pay_line(kind): return random.choice(PAY_CALM if kind == "emergency" else PAY)

# def audience(mid):
#     m = q("select organiser_id, recipient_id, surprise from moments where id=?", (mid,), one=True)
#     if not m: return []
#     ids = [m["organiser_id"]] + [r["user_id"] for r in q("select user_id from members where moment_id=?", (mid,))]
#     if not m["surprise"]: ids.append(m["recipient_id"])  # a surprise recipient hears nothing at all
#     return list(dict.fromkeys(ids))

# def notify(uids, body, mid=None, icon="🔔"):
#     t = q("select occasion from moments where id=?", (mid,), one=True) if mid else None
#     for x in set(uids): q("insert into notifs(user_id,moment_id,icon,title,body) values(?,?,?,?,?)", (x, mid, icon, t["occasion"] if t else "", body), w=True)

# def say(mid, body, kind="system", uid=0, skip=()):
#     q("insert into chat(moment_id,user_id,kind,body) values(?,?,?,?)", (mid, uid, kind, body), w=True)
#     if kind == "pay":
#         ic, title, _ = (body.split("|") + ["", "", ""])[:3]
#         notify([x for x in audience(mid) if x != uid and x not in skip], title, mid, ic)

# def last_msg(mid):
#     r = q("select body,kind from chat where moment_id=? order by id desc limit 1", (mid,), one=True)
#     return "" if not r else (r["body"].split("|")[1] if r["kind"] == "pay" else r["body"][:80])

# def chat_access(mid, u):
#     m, org, rec = access(mid, u)
#     member = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
#     if not (org or member or rec) or m["status"] == "draft":
#         raise HTTPException(403, "The group chat opens once the organiser sends the message")
#     return m

# @app.get("/api/moments/{mid}/chat")
# def chat(mid: int, after: int = 0, u=Depends(me)):
#     try: chat_access(mid, u)
#     except HTTPException: return []
#     names = {r["id"]: r["name"] for r in q("select id,name from users")}
#     return [{"id": r["id"], "kind": r["kind"], "body": r["body"], "uid": r["user_id"], "name": names.get(r["user_id"], ""), "ts": r["ts"]} for r in q("select * from chat where moment_id=? and id>? order by id", (mid, after))]

# class Say(BaseModel): text: str

# class ChatSuggestion(BaseModel): kind: str

# @app.post("/api/moments/{mid}/chat/suggest")
# async def chat_suggest(mid: int, b: ChatSuggestion, u=Depends(me)):
#     m = chat_access(mid, u)
#     org = m["organiser_id"] == u["id"]
#     rec = m["recipient_id"] == u["id"] and not m["surprise"]
#     member = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
#     if b.kind == "thanks":
#         if not (org or rec): raise HTTPException(403, "Only the organiser or recipient can use this thank-you message")
#         prompt = f"Write a sincere, natural thank-you message (35-60 words) from {u['name']} to everyone who contributed to '{m['occasion']}'. This is an {'emergency fund' if m['kind']=='emergency' else 'group occasion fund'}. {'Keep it calm and heartfelt; acknowledge that people showed up during a difficult time, without sounding celebratory.' if m['kind']=='emergency' else 'Make it warm and appreciative.'} Do not claim a specific amount or promise anything. Output only the message."
#     elif b.kind in ("congratulate", "support"):
#         if not member or org or rec: raise HTTPException(403, "This option is for contributors")
#         if m["kind"] == "emergency" and b.kind != "support": raise HTTPException(400, "Use a supportive message for an emergency fund")
#         if m["kind"] != "emergency" and b.kind != "congratulate": raise HTTPException(400, "Use a congratulatory message for this occasion")
#         prompt = f"Write a personal message (30-55 words) from {u['name']} to the recipient {q('select name from users where id=?',(m['recipient_id'],),one=True)['name']} for '{m['occasion']}'. {'This is an emergency. Be gentle, compassionate and practical; do not congratulate, minimize the situation, or console the contributor. Address the recipient directly.' if m['kind']=='emergency' else 'Congratulate the recipient warmly and naturally.'} Do not mention fundraising mechanics or invent facts. Output only the message."
#     else:
#         raise HTTPException(400, "Unknown message option")
#     result = await ai(prompt)
#     if not result:
#         if b.kind == "thanks": result = "Thank you for showing up and helping us through this. Your kindness means more than words can say. We are grateful to have you beside us."
#         elif b.kind == "support": result = "I’m thinking of you and your family. I hope you have the support and space you need right now. Please know you are not facing this alone."
#         else: result = f"Congratulations on {m['occasion']}! I’m so happy for you and hope this moment brings you plenty of joy."
#     return {"message": result.strip()[:700], "ai": AI_ERR["ok"]}

# @app.post("/api/moments/{mid}/chat")
# async def post_chat(mid: int, b: Say, bg: BackgroundTasks, u=Depends(me)):
#     chat_access(mid, u); t = b.text.strip()[:500]
#     if not t: raise HTTPException(400, "Say something first")
#     say(mid, t, "text", u["id"])
#     if re.match(r"@pip\b", t, re.I): bg.add_task(pip_reply, mid, u["name"], t[4:])  # Pip answers a moment later, sending never waits on the AI
#     return {"ok": True}

# async def pip_reply(mid, who, ask):
#     try:
#         m = q("select * from moments where id=?", (mid,), one=True)
#         if not m: return
#         _, col, _, left = totals(mid)
#         r = await ai(f"You are Pip, a warm, witty assistant inside a group chat raising money for '{m['occasion']}' (details: {m['description']} {m['context']}). Goal ${m['target']:.0f}, raised ${col:.2f}. {'It is a SURPRISE: never hint to the recipient.' if m['surprise'] else ''} Answer {who} in max 60 words, specific and useful: {ask}")
#         say(mid, r or "Pip is catching a nap (add a Gemini key and I'll wake up). Meanwhile: every amount counts, and the ring shows how close you are.", "ai")
#     except Exception as e: print("[Pip]", e)

# def launch(mid, u):
#     m = q("select * from moments where id=?", (mid,), one=True)
#     say(mid, m["message"], "text", u["id"])
#     notify([r["user_id"] for r in q("select user_id from members where moment_id=?", (mid,))], f"{u['name']} invited you to give to {m['occasion']}", mid, "💌")
#     if not m["surprise"]:
#         icon = "🤍" if m["kind"] == "emergency" else "💝"
#         title = (
#             f"{u['name']} started an emergency fund for you: {m['occasion']}"
#             if m["kind"] == "emergency"
#             else f"{u['name']} started a moment for you: {m['occasion']}"
#         )
#         notify([m["recipient_id"]], title, mid, icon)
# async def launch_ai(mid):
#     try:
#         m = q("select * from moments where id=?", (mid,), one=True)
#         if not m: return
#         mems = [r["name"] for r in q("select u.name from members x join users u on u.id=x.user_id where x.moment_id=?", (mid,))]
#         emer = m["kind"] == "emergency"
#         rec = q("select name from users where id=?", (m["recipient_id"],), one=True)["name"]
#         w = await ai(f"You are Pip, a {'calm, steady and caring' if emer else 'warm'} assistant. Write a short welcome (max 45 words) for the new group chat for '{m['occasion']}'. Say: give any amount you like, every payment appears here live, no fixed shares. {'This is an emergency fund: keep the tone calm and supportive, never celebratory or playful, no party emoji.' if emer else ''} {'Remind everyone it is a surprise.' if m['surprise'] else ''}")
#         say(mid, w or ("Welcome in. Give whatever feels right, there are no fixed shares. Every contribution lands right here, live." if emer else "Welcome in! Give whatever feels right, there are no fixed shares. Every payment lands right here, live. ✨"), "ai")
#         if emer:
#             # Emergency encouragement is addressed to the affected recipient, never to contributors.
#             support = await ai(f"Write one short, gentle message (max 30 words) addressed directly to {rec}, the person affected by this emergency. The organiser is {'also the recipient' if m['organiser_id'] == m['recipient_id'] else 'someone organising support for the recipient'}. Speak to {rec} as the person receiving support. Never address or console contributors such as {', '.join(mems) or 'group members'}. No congratulations, no party language, no assumptions about recovery. Output only the message.")
#             if support: say(mid, support, "ai")
#         else:
#             notes = await ai(f'Who is who: "{m["context"]}". Members: {mems}. For each member write one friendly personal nudge (max 20 words) that references their relationship to the recipient when the text mentions it, otherwise keep it warm and generic. Return a JSON object mapping name to note.', True)
#             if isinstance(notes, dict):
#                 for n, t in list(notes.items())[:6]: say(mid, str(t) if str(t).lower().startswith(str(n).lower()) else f"{n}, {t}", "ai")
#     except Exception as e: print("[Pip welcome]", e)

# async def celebrate(mid, u, amt, to_org=False, bg=None):
#     m = q("select * from moments where id=?", (mid,), one=True); col = totals(mid)[1]
#     say(mid, f"💸|{u['name']} gave ${amt:.2f}|{pay_line(m['kind'])} {'Straight into the organiser PayPal.' if to_org else 'Held safely in the MomentPay wallet.'}", "pay", u["id"])
#     notify([u["id"]], f"You contributed ${amt:.2f}", mid, "💸")
#     for th, word in ((0.5, "halfway"), (1, "fully funded")):
#         if (col - amt) / m["target"] < th <= col / m["target"]:
#             if bg is not None: bg.add_task(cheer, mid, th, word, col, m["target"], m["occasion"], m["kind"])
#             else: await cheer(mid, th, word, col, m["target"], m["occasion"], m["kind"])

# async def cheer(mid, th, word, col, target, occasion, kind="occasion"):
#     try:
#         if kind == "emergency":
#             t = await ai(f"Write one calm, caring sentence (max 25 words, NOT celebratory, no party emoji) for a group chat: an emergency fund for '{occasion}' just reached {word} (${col:.0f} of ${target:.0f}). Name no individual.")
#             say(mid, t or ("Halfway to the goal. Thank you for standing with them." if th < 1 else "The goal has been reached. The organiser can take it from here."), "ai")
#         else:
#             t = await ai(f"Write one joyful sentence (max 25 words) for a group chat: the fund for '{occasion}' just became {word} (${col:.0f} of ${target:.0f}). Name no individual.")
#             say(mid, t or ("Halfway there! The tide is turning. 🌊" if th < 1 else "We did it. The goal is met, and the organiser can take it from here. 🎉"), "ai")
#     except Exception as e: print("[Pip cheer]", e)

# class Regen(BaseModel): tone: str = "warm"

# @app.post("/api/moments/{mid}/regenerate")
# async def regen(mid: int, b: Regen, u=Depends(me)):
#     m = organiser_only(mid, u, ["draft"])
#     n = {r["id"]: r["name"] for r in q("select id,name from users")}
#     s_ = SimpleNamespace(kind=m["kind"], occasion=m["occasion"], description=m["description"], context=m["context"], target=m["target"], tone=b.tone)
#     t = await make_message(s_, n[m["organiser_id"]], n[m["recipient_id"]], m["surprise"], mid, m["organiser_id"] == m["recipient_id"])
#     ok = AI_ERR["ok"]; q("update moments set message=?, ai_ok=? where id=?", (t, int(ok), mid), w=True); return {"message": t, "ai": ok, "err": AI_ERR["msg"]}

# @app.get("/api/moments/{mid}/ideas")
# async def ideas(mid: int, u=Depends(me)):
#     m = organiser_only(mid, u, ["funded", "asking", "answered"])
#     _no_emergency_extras(m)
#     r = await ai(f"Gift for '{m['occasion']}'. Context: {m['description']} {m['context']}. Budget ${totals(mid)[3]:.0f}. Suggest 5 concrete everyday product search phrases (1-3 words each) that suit the person. Return a JSON list of strings.", True)
#     return [x for x in r if isinstance(x, str)][:5] if isinstance(r, list) else ["backpack", "watch", "headphones", "lamp", "kitchen"]

# _AIST = {"t": 0.0, "r": None}
# @app.get("/api/ai/status")
# async def ai_status():
#     if _AIST["r"] and time.time() - _AIST["t"] < (300 if _AIST["r"]["ok"] else 30): return _AIST["r"]  # not a live AI call on every page load
#     r = await ai("Reply with exactly one word: ready")
#     res = {"ok": bool(r), "error": "" if r else AI_ERR["msg"]}
#     _AIST.update(t=time.time(), r=res); return res

# def _purge(mid):
#     for t in ("chat", "members", "contributions", "purchases", "payouts", "notifs"): q(f"delete from {t} where moment_id=?", (mid,), w=True)
#     q("delete from moments where id=?", (mid,), w=True)

# def _notify_removed(m, u):
#     ids = [r["user_id"] for r in q("select user_id from members where moment_id=?", (m["id"],))]
#     if not m["surprise"] and m["status"] != "draft": ids.append(m["recipient_id"])
#     notify([x for x in ids if x != u["id"]], f"{u['name']} removed the moment '{m['occasion']}'", None, "🗑")

# @app.delete("/api/moments/{mid}")
# def delete_moment(mid: int, u=Depends(me)):
#     m, org, _ = access(mid, u)
#     if not org: raise HTTPException(403, "Only the organiser can delete this moment")
#     if totals(mid)[3] > 0.005: raise HTTPException(400, "There is still money in the pool. Send it on or return it to contributors first.")
#     _notify_removed(m, u); _purge(mid); return {"ok": True}

# @app.get("/api/ai/check")
# async def ai_check():
#     t = await ai("Reply with the single word: ready")
#     return {"ok": bool(t), "reply": t, "last_error": AI_ERR["msg"], "gemini_key": bool(GKEY), "groq_key": bool(GROQ_KEY), "search": "google_shopping" if SERP else "demo_catalog"}

# @app.get("/api/notifications")
# def notifications(u=Depends(me)):
#     rows = q("select * from notifs where user_id=? order by id desc limit 60", (u["id"],))
#     return {"items": [dict(r) for r in rows], "unread": q("select count(*) c from notifs where user_id=? and seen=0", (u["id"],), one=True)["c"]}

# @app.post("/api/notifications/read")
# def notifications_read(u=Depends(me)):
#     q("update notifs set seen=1 where user_id=?", (u["id"],), w=True); return {"ok": True}

# @app.get("/api/pulse")
# def pulse(moment: int = 0, after: int = 0, u=Depends(me)):
#     """One tiny call replaces the separate chat, moment and notification polls."""
#     n = q("select max(id) top, sum(seen=0) unread from notifs where user_id=?", (u["id"],), one=True)
#     out = {"top": n["top"] or 0, "unread": n["unread"] or 0, "chat": [], "sig": None}
#     if moment:
#         try:
#             m, _, _ = access(moment, u)
#             _, col, _, left = totals(moment)
#             out["sig"] = [m["status"], col, left, m["recipient_choice"], q("select count(*) c from purchases where moment_id=?", (moment,), one=True)["c"], q("select count(*) c from payouts where moment_id=?", (moment,), one=True)["c"]]
#             out["chat"] = chat(moment, after, u)
#         except HTTPException: out["gone"] = True
#     return out

# class DelAcct(BaseModel): password: str

# @app.post("/api/profile/delete")
# def delete_account(b: DelAcct, u=Depends(me)):
#     if h(b.password) != u["pw"]: raise HTTPException(400, "That password is not right")
#     uid = u["id"]
#     rows = q("select * from moments where organiser_id=? or recipient_id=? or id in (select moment_id from contributions where user_id=?)", (uid, uid, uid))
#     busy = [m["occasion"] for m in rows if totals(m["id"])[3] > 0.005]
#     if busy: raise HTTPException(400, "Money is still in play in: " + ", ".join(busy[:4]) + ". Send it on or return it first, then delete your account.")
#     for m in rows:
#         if m["organiser_id"] == uid: _notify_removed(m, u); _purge(m["id"])
#     q("delete from members where user_id=?", (uid,), w=True); q("delete from notifs where user_id=?", (uid,), w=True); q("delete from users where id=?", (uid,), w=True)
#     return {"ok": True}

# app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True))



"""MomentPay backend (FastAPI). Free stack: PayPal Sandbox, Gemini free tier, DummyJSON + FakeStore APIs, SQLite."""
import os, json, base64, time, secrets, hashlib, sqlite3, uuid, re, asyncio
from collections import defaultdict
from contextlib import closing
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Header, HTTPException, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
PP_ID, PP_SECRET = os.getenv("PAYPAL_CLIENT_ID", ""), os.getenv("PAYPAL_CLIENT_SECRET", "")
PP = "https://api-m.sandbox.paypal.com"
# Contributions are collected straight into the ORGANISER's PayPal account. Set to false to collect into the app's own sandbox business wallet instead.
COLLECT_TO_ORGANISER = os.getenv("COLLECT_TO_ORGANISER", "true").lower() == "true"
GKEY, GMODEL = os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GROQ_KEY, GROQ_MODEL = os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
BASE = os.getenv("BASE_URL", "http://localhost:8000")
FALLBACK = os.getenv("DEMO_FALLBACK", "true").lower() == "true"
DB = os.getenv("DB_PATH", "momentpay.db")

SCHEMA = """
create table if not exists users(id integer primary key, name text, email text unique, paypal_email text, pw text, token text);
create table if not exists moments(id integer primary key, organiser_id int, recipient_id int, kind text, occasion text, description text, context text, surprise int, target real, status text default 'draft', message text, recipient_choice text, recipient_spec text);
create table if not exists members(moment_id int, user_id int);
create table if not exists contributions(id integer primary key, moment_id int, user_id int, amount real, order_id text);
create table if not exists purchases(id integer primary key, moment_id int, title text, store text, price real, reasoning text, order_id text, status text);
create table if not exists payouts(id integer primary key, moment_id int, user_id int, amount real, kind text, batch_id text, status text);
create table if not exists events(id integer primary key, body text);
create table if not exists notifs(id integer primary key, user_id int, moment_id int, icon text, title text, body text, ts text default (datetime('now')), seen int default 0);
create table if not exists chat(id integer primary key, moment_id int, user_id int, kind text, body text, ts text default (datetime('now')));
"""

def q(sql, a=(), one=False, w=False):
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(sql, a)
        if w:
            c.commit(); return cur.lastrowid
        r = cur.fetchall()
        return (r[0] if r else None) if one else r

with closing(sqlite3.connect(DB)) as _c:
    _c.executescript(SCHEMA)
    try: _c.execute("pragma journal_mode=wal")  # readers no longer wait on writers, so polling and saving stop blocking each other
    except sqlite3.OperationalError: pass
    for _st in ("alter table moments add column ai_ok int default 0", "alter table purchases add column link text default ''",
                "alter table users add column phone text default ''", "alter table users add column city text default ''", "alter table users add column about text default ''"):
        try: _c.execute(_st)
        except sqlite3.OperationalError: pass

app = FastAPI(title="MomentPay")

# ---------- auth ----------
def h(pw): return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"momentpay-demo", 100_000).hex()
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

def me(authorization: str = Header("")):
    u = q("select * from users where token=?", (authorization,), one=True) if authorization else None
    if not u: raise HTTPException(401, "Please log in")
    return u

class Auth(BaseModel):
    email: str; password: str; name: str = ""; paypal_email: str = ""

@app.post("/api/register")
def register(b: Auth):
    if not (b.name and b.email and b.paypal_email and b.password): raise HTTPException(400, "Fill in every field")
    if not (EMAIL_RE.fullmatch(b.email) and EMAIL_RE.fullmatch(b.paypal_email)): raise HTTPException(400, "Enter valid email addresses")
    if q("select 1 from users where email=?", (b.email.lower(),), one=True): raise HTTPException(400, "Email already registered")
    t = secrets.token_hex(16)
    q("insert into users(name,email,paypal_email,pw,token) values(?,?,?,?,?)", (b.name, b.email.lower(), b.paypal_email, h(b.password), t), w=True)
    return {"token": t}

@app.post("/api/login")
def login(b: Auth):
    u = q("select * from users where email=? and pw=?", (b.email.lower(), h(b.password)), one=True)
    if not u: raise HTTPException(401, "Wrong email or password")
    return {"token": u["token"]}

@app.get("/api/me")
def whoami(u=Depends(me)): return {"id": u["id"], "name": u["name"], "email": u["email"]}

@app.get("/api/users")
def users(q_: str = "", u=Depends(me)):
    t = q_.strip().lower()
    if len(t) < 2: return []  # no browsing the user list: search by name, or exact email
    rows = q("select id,name,email from users where id!=? and (lower(name) like ? or email=?) limit 8", (u["id"], f"%{t}%", t))
    return [{"id": r["id"], "name": r["name"], "email": r["email"][0] + "***" + r["email"][r["email"].index("@"):]} for r in rows]

@app.get("/api/config")
def config(): return {"client_id": PP_ID, "ai": bool(GKEY or GROQ_KEY), "search": "channel3" if os.getenv("CHANNEL3_API_KEY") else "google" if os.getenv("SERPAPI_KEY") else "demo", "collect_org": COLLECT_TO_ORGANISER}

# ---------- profile ----------
class Profile(BaseModel):
    name: str; email: str; paypal_email: str; phone: str = ""; city: str = ""; about: str = ""

def _clean_profile(b):
    name, email, pe = b.name.strip(), b.email.strip().lower(), b.paypal_email.strip()
    phone, city, about = b.phone.strip(), b.city.strip(), b.about.strip()
    if not (2 <= len(name) <= 60) or not re.search(r"[^\W\d_]", name) or re.search(r"[<>]", name): raise HTTPException(400, "Enter your real name (2 to 60 characters, with letters)")
    if not EMAIL_RE.fullmatch(email): raise HTTPException(400, "Enter a valid login email")
    if not EMAIL_RE.fullmatch(pe): raise HTTPException(400, "Enter a valid PayPal email")
    if phone and not (re.fullmatch(r"\+?[0-9 ()\-.]{7,20}", phone) and 7 <= len(re.sub(r"\D", "", phone)) <= 15): raise HTTPException(400, "Enter a valid phone number, for example +91 98765 43210")
    if len(city) > 60: raise HTTPException(400, "City is too long (60 characters at most)")
    if len(about) > 280: raise HTTPException(400, "The about line is too long (280 characters at most)")
    return name, email, pe, phone, city, about

@app.get("/api/profile")
def get_profile(u=Depends(me)):
    return {k: u[k] or "" for k in ("name", "email", "paypal_email", "phone", "city", "about")}

@app.put("/api/profile")
def put_profile(b: Profile, u=Depends(me)):
    name, email, pe, phone, city, about = _clean_profile(b)
    if q("select 1 from users where email=? and id!=?", (email, u["id"]), one=True): raise HTTPException(400, "That email already belongs to another account")
    q("update users set name=?, email=?, paypal_email=?, phone=?, city=?, about=? where id=?", (name, email, pe, phone, city, about, u["id"]), w=True)
    return {"ok": True}

# ---------- helpers ----------
def split(total_cents, weights):
    """Proportional split in cents using largest remainder, so shares always add up exactly."""
    s = sum(weights.values()); raw = {k: total_cents * w / s for k, w in weights.items()}
    base = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[: total_cents - sum(base.values())]: base[k] += 1
    return base

def totals(mid):
    cs = q("select user_id, sum(amount) a from contributions where moment_id=? group by user_id", (mid,))
    col = round(sum(c["a"] for c in cs), 2)
    spent = round(sum(r["price"] for r in q("select price from purchases where moment_id=?", (mid,))), 2)
    out = round(sum(r["amount"] for r in q("select amount from payouts where moment_id=?", (mid,))), 2)
    return cs, col, spent, round(col - spent - out, 2)

def access(mid, u):
    m = q("select * from moments where id=?", (mid,), one=True)
    if not m: raise HTTPException(404, "Moment not found")
    org = m["organiser_id"] == u["id"]
    mem = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
    rec = m["recipient_id"] == u["id"] and not m["surprise"] and m["status"] != "draft"
    if mem and not org and m["status"] == "draft": raise HTTPException(403, "The organiser has not opened this group yet. You will be notified when it is ready.")
    if not (org or (mem and m["status"] != "draft") or rec): raise HTTPException(403, "No access to this moment")
    return m, org, rec

def organiser_only(mid, u, statuses):
    m, org, _ = access(mid, u)
    if not org: raise HTTPException(403, "Only the organiser can do this")
    if m["status"] not in statuses: raise HTTPException(400, f"Not possible while status is '{m['status']}'")
    return m

# ---------- PayPal (sandbox) ----------
_tok = {"v": None, "exp": 0}
async def pp(method, path, body=None):
    if not PP_ID: raise HTTPException(500, "PayPal keys missing in .env")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            if time.time() > _tok["exp"]:
                r = await c.post(PP + "/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=(PP_ID, PP_SECRET))
                if r.status_code != 200: raise HTTPException(502, "PayPal authentication failed - check your keys")
                _tok.update(v=r.json()["access_token"], exp=time.time() + r.json()["expires_in"] - 60)
            r = await c.request(method, PP + path, json=({} if body is None and method == "POST" else body), headers={"Authorization": "Bearer " + _tok["v"], "Content-Type": "application/json"})
    except httpx.HTTPError: raise HTTPException(502, "Could not reach PayPal. Check your internet connection.")
    try: j = r.json()
    except Exception: j = {}
    if r.status_code >= 300:
        iss = "; ".join(f"{d.get('issue', '')} {d.get('description', '')}".strip() for d in (j.get("details") or []) if isinstance(d, dict))
        print(f"[PayPal] {method} {path} -> {r.status_code}: {r.text[:600]}")
        raise HTTPException(502, "PayPal: " + (str(j.get("message") or j.get("name") or r.text) + (" - " + iss if iss else ""))[:300])
    return j

async def payouts(mid, items, kind):
    """items: [(user_id, paypal_email, amount)] -> records payouts. Falls back to simulation if Payouts isn't enabled."""
    body = {"sender_batch_header": {"sender_batch_id": f"mp{mid}-{uuid.uuid4().hex[:10]}", "email_subject": "You received money via MomentPay"},
            "items": [{"recipient_type": "EMAIL", "receiver": e, "amount": {"value": f"{a:.2f}", "currency": "USD"}, "sender_item_id": f"{kind}-{i}"} for i, (_, e, a) in enumerate(items)]}
    try:
        bid, st = (await pp("POST", "/v1/payments/payouts", body))["batch_header"]["payout_batch_id"], "sent"
    except HTTPException:
        if not FALLBACK: raise
        bid, st = "SIM-" + uuid.uuid4().hex[:8], "simulated"
    for uid, _, a in items: q("insert into payouts(moment_id,user_id,amount,kind,batch_id,status) values(?,?,?,?,?,?)", (mid, uid, a, kind, bid, st), w=True)

class Contrib(BaseModel):
    moment_id: int; amount: float = 0; order_id: str = ""

@app.post("/api/paypal/create-order")
async def create_order(b: Contrib, u=Depends(me)):
    m, _, rec = access(b.moment_id, u)
    if m["recipient_id"] == u["id"]: raise HTTPException(403, "This moment is for you, so you can't contribute to it.")
    if m["status"] != "active": raise HTTPException(400, "This fund is not open for contributions")
    if b.amount <= 0: raise HTTPException(400, "Enter an amount above zero")
    org = q("select paypal_email from users where id=?", (m["organiser_id"],), one=True)
    unit = {"reference_id": f"moment-{m['id']}", "description": m["occasion"][:120], "amount": {"currency_code": "USD", "value": f"{b.amount:.2f}"}}
    # PayPal refuses to let an account pay itself, so the organiser's own contribution skips the payee override and lands as a normal capture in the app's own sandbox business wallet instead.
    if COLLECT_TO_ORGANISER and m["organiser_id"] != u["id"]: unit["payee"] = {"email_address": org["paypal_email"]}
    try: o = await pp("POST", "/v2/checkout/orders", {"intent": "CAPTURE", "purchase_units": [unit]})
    except HTTPException as e:
        if "payee" in str(e.detail).lower(): raise HTTPException(400, "PayPal cannot pay the organiser's PayPal email. It must be a sandbox Business account (or set COLLECT_TO_ORGANISER=false).")
        raise
    return {"id": o["id"]}

@app.post("/api/paypal/capture-order")
async def capture(b: Contrib, bg: BackgroundTasks, u=Depends(me)):
    m, _, _ = access(b.moment_id, u)
    if m["recipient_id"] == u["id"]: raise HTTPException(403, "This moment is for you, so you can't contribute to it.")
    org = q("select paypal_email from users where id=?", (m["organiser_id"],), one=True)
    if q("select 1 from contributions where order_id=?", (b.order_id,), one=True): return {"ok": True, "amount": 0, "to_organiser": True}
    r = await pp("POST", f"/v2/checkout/orders/{b.order_id}/capture")  # money only moves HERE, not when the buyer approves
    if r.get("status") != "COMPLETED": raise HTTPException(400, "PayPal did not complete the payment, so nothing was charged")
    amt = float(r["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"])
    to_org = (r["purchase_units"][0].get("payee") or {}).get("email_address", "").lower() == org["paypal_email"].lower()
    q("insert into contributions(moment_id,user_id,amount,order_id) values(?,?,?,?)", (b.moment_id, u["id"], amt, b.order_id), w=True)
    await celebrate(b.moment_id, u, amt, to_org, bg)
    return {"ok": True, "amount": amt, "to_organiser": to_org}

@app.post("/api/paypal/webhook")
async def webhook(r: Request):
    q("insert into events(body) values(?)", ((await r.body()).decode()[:4000],), w=True)
    return {"ok": True}

# ---------- AI (Gemini free tier, with graceful fallbacks) ----------
AI_ERR = {"ok": False, "msg": ""}
_dead = {}  # model/provider -> (retry_after, message): a retired model or a rate limit is skipped for a while instead of costing a round trip on every call
async def ai(prompt, as_json=False):
    """Gemini first, then Groq (both free tiers). Failures are recorded in AI_ERR so the UI can say why, never silent."""
    AI_ERR.update(ok=False, msg="")
    def parse(t):
        t = t.strip()
        if not as_json: return t
        v = json.loads(re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip())
        if isinstance(v, dict) and len(v) == 1 and isinstance(next(iter(v.values())), list): v = next(iter(v.values()))
        return v
    def burn(key, code, msg):
        if code != 200: _dead[key] = (time.time() + (900 if code in (400, 401, 403, 404) else 30), msg)
    async with httpx.AsyncClient(timeout=25) as c:
        if GKEY:
            for model in dict.fromkeys([GMODEL, "gemini-flash-latest", "gemini-flash-lite-latest"]):
                d = _dead.get(model)
                if d and d[0] > time.time(): AI_ERR["msg"] = d[1]; continue
                j, code = {}, 0
                try:
                    r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": GKEY},
                                     json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"} if as_json else {}})
                    code, j = r.status_code, r.json()
                    if code != 200: raise ValueError(f"HTTP {code} {str((j.get('error') or {}).get('message', r.text))[:160]}")
                    v = parse("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))); AI_ERR["ok"] = True; return v
                except Exception as e:
                    AI_ERR["msg"] = f"Gemini ({model}): {(j.get('error') or {}).get('message') or repr(e)}"[:220]; burn(model, code, AI_ERR["msg"])
        if GROQ_KEY:
            d = _dead.get("groq")
            if d and d[0] > time.time(): AI_ERR["msg"] = d[1]
            else:
                j, code = {}, 0
                try:
                    r = await c.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + GROQ_KEY},
                                     json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], **({"response_format": {"type": "json_object"}} if as_json else {})})
                    code, j = r.status_code, r.json(); v = parse(j["choices"][0]["message"]["content"]); AI_ERR["ok"] = True; return v
                except Exception as e:
                    AI_ERR["msg"] = f"Groq: {(j.get('error') or {}).get('message') or repr(e)}"[:220]; burn("groq", code, AI_ERR["msg"])
    if not (GKEY or GROQ_KEY): AI_ERR["msg"] = "No AI key found. Add GEMINI_API_KEY or GROQ_API_KEY to .env"
    return None

# ---------- Pip AI planning companion ----------
class PlannerChat(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    context: dict | None = None

def _planner_text(value, limit=1500):
    if value is None: return ""
    if isinstance(value, (str, int, float)): return str(value).strip()[:limit]
    return ""

def _clean_planner_plan(plan, index):
    """Validate planner estimates. Missing/invalid costs are never silently shown as zero."""
    if not isinstance(plan, dict): return None
    title = _planner_text(plan.get("title"), 100)
    concept = _planner_text(plan.get("concept"), 1500)
    if not title or not concept: return None

    def clean_list(value):
        if not isinstance(value, list): return []
        return [_planner_text(x, 250) for x in value[:8] if _planner_text(x, 250)]

    try:
        budget = float(plan.get("budget"))
        if not (0 < budget <= 100000000): return None
    except (TypeError, ValueError):
        return None

    raw = plan.get("budget_breakdown", {})
    clean = {}
    if isinstance(raw, dict):
        for key, value in list(raw.items())[:10]:
            try:
                amount = float(value)
                label = _planner_text(key, 80)
                if label and 0 < amount <= 100000000: clean[label] = round(amount, 2)
            except (TypeError, ValueError):
                pass
    # A structured plan without any itemised costs is not useful for a money-planning app.
    if not clean: return None
    # Use the itemised sum as the displayed total so the numbers always reconcile.
    itemised_total = round(sum(clean.values()), 2)
    if itemised_total <= 0: return None
    budget = itemised_total

    currency = _planner_text(plan.get("currency"), 3).upper()
    # MomentPay uses USD end-to-end (planner display, fundraising target and PayPal).
    # Reject non-USD plans rather than silently relabelling rupee/euro amounts as dollars.
    if currency != "USD":
        return None

    def optional_amount(key):
        try:
            value = float(plan.get(key))
            return round(value, 2) if 0 < value <= 100000000 else None
        except (TypeError, ValueError):
            return None

    try:
        people_count = int(plan.get("people_count")) if plan.get("people_count") is not None else None
        if people_count is not None and not (1 <= people_count <= 10000): people_count = None
    except (TypeError, ValueError):
        people_count = None

    low_value = optional_amount("budget_min")
    high_value = optional_amount("budget_max")
    if low_value is not None and high_value is not None:
        low_value, high_value = min(low_value, high_value), max(low_value, high_value)
        if high_value <= low_value * 1.02:
            low_value = high_value = None
        else:
            low_value = min(low_value, budget)
            high_value = max(high_value, budget)
    else:
        low_value = high_value = None

    return {
        "id": _planner_text(plan.get("id"), 40) or f"plan-{index}",
        "title": title,
        "tagline": _planner_text(plan.get("tagline"), 200),
        "concept": concept,
        "activities": clean_list(plan.get("activities")),
        "items": clean_list(plan.get("items")),
        "budget": round(budget, 2),
        "currency": currency,
        "budget_min": low_value,
        "budget_max": high_value,
        "budget_breakdown": clean,
        "cost_note": _planner_text(plan.get("cost_note"), 500),
        "people_count": people_count,
        "per_person": round(budget / people_count, 2) if people_count else None,
        "timeline": _planner_text(plan.get("timeline"), 1000),
        "why_it_fits": _planner_text(plan.get("why_it_fits"), 800),
    }

@app.post("/api/planner/chat")
async def planner_chat(b: PlannerChat, u=Depends(me)):
    message=_planner_text(b.message,1000)
    if not message: raise HTTPException(400,"Please tell Pip what is on your mind.")
    history=[]
    for item in (b.history or [])[-12:]:
        if isinstance(item,dict) and item.get("role") in ("user","assistant"):
            content=_planner_text(item.get("content"),800)
            if content: history.append({"role":item["role"],"content":content})
    context=b.context if isinstance(b.context,dict) else {}
    convo="\n".join(f"{x['role'].upper()}: {x['content']}" for x in history)
    context_text=json.dumps(context,ensure_ascii=False)[:4500]
    profile_city = _planner_text(u["city"], 80) if "city" in u.keys() else ""
    prompt=f'''You are Pip, the planning companion inside MomentPay. Your job is to be a genuinely thoughtful, capable friend who helps people make good decisions. You are not a customer-service agent, motivational speaker, therapist, lecturer, salesperson or questionnaire.

HOW TO BE A GOOD FRIEND:
- Listen to the actual message and respond to its meaning, not just its keywords.
- Be warm, natural, grounded and emotionally intelligent. Sound like a smart friend, not a scripted assistant.
- Do not overdo emojis, praise, sympathy, pet names, exclamation marks or dramatic language. Usually use zero or one emoji.
- Do not repeat greetings or sympathy in every turn. Acknowledge a difficult situation once, then help.
- Do not be over-smart, preachy, pushy, overly familiar or falsely confident. If you do not know, say so plainly.
- Keep ordinary replies to roughly 2-6 short sentences. Use short bullets only when they make a decision clearer. Avoid essay-like paragraphs.
- Answer the user's direct question first. Do not repeat background information they already know.
- Ask at most ONE useful follow-up question at a time. Do not ask questions whose answers are already in the conversation.
- Make sensible suggestions proactively. Offer a recommendation with a short reason, not a huge menu of generic ideas.
- Respect the user's budget, preferences, culture, constraints and decisions. If a budget is unrealistic, explain gently and suggest a workable alternative.
- Use the conversation history and context as memory. Never pretend to remember details that are not present.

SITUATION AWARENESS:
- Identify the moment type from the whole conversation: celebration, birthday, anniversary, wedding, travel, farewell, appreciation, emergency, medical support, fundraising, or other.
- Celebration: be cheerful and imaginative, but practical. Tailor ideas to the recipient and budget.
- Emergency/medical/financial hardship: become calm, compassionate and direct. No party language, celebratory emojis, playful tone or sales pitch. Prioritise immediate practical next steps.
- Medical costs: distinguish procedures accurately (for example, stent/angioplasty is not the same as bypass or valve surgery). Do not combine their costs or claim a generic estimate is reliable. Actual costs depend on procedure, number/type of stents, hospital, city, room/ICU, tests and complications. If the hospital quote is unknown, say that clearly and ask for the quote or hospital/city only if it materially helps. Do not make up insurance coverage percentages, guarantees, or confirmed aid eligibility. Never replace medical advice from the treating team.
- If the user asks how much four people should contribute, calculate the group target and each person's share explicitly. Check the arithmetic before answering.

COST ESTIMATION — THIS IS A CORE MOMENTPAY FEATURE:
- A plan with a missing, zero or vague budget is NOT a complete plan. Never output zero as a substitute for an unknown price.
- Whenever suggesting a real-world plan, give a realistic estimated total and an itemised breakdown with numeric amounts. Make the line items add up to the total (small rounding differences only).
- MomentPay uses USD consistently. ALWAYS express every plan budget, low/high range, per-person amount and every budget_breakdown line item in USD, regardless of the user's country or the currency they mention. Set currency="USD". Never return INR, GBP, EUR or another currency.
- You may use the user's country/city to reason about realistic local costs, but express the resulting estimate in USD. If the user gives a budget in another currency, convert it approximately to USD and state the assumed conversion rate in cost_note; never silently relabel the original number as dollars. If you cannot make a defensible conversion, ask one concise follow-up instead of inventing a target.
- The organiser's saved profile city, if supplied below, is the preferred location for local estimates unless the user states another location. If no city is supplied or mentioned, use broad country-level estimates and explicitly say they are not city-specific. NEVER invent a city (for example, Delhi) or claim estimates are based on local vendors there.
- Provide a realistic low/high range when prices genuinely vary. Do not set budget_min and budget_max to the same value just to create a range. If you cannot justify a range, set both to null and show one clearly labelled approximate estimate. The itemised breakdown should add up to the central estimate (budget), not to an arbitrary endpoint.
- Include a concise cost_note stating assumptions and that prices are estimates, not confirmed vendor quotes. Do not claim live prices, availability or bookings unless a connected live source actually supplied them.
- Use realistic local cost categories. For a birthday in India, reason from plausible local cake, food, decoration, venue/transport/gift costs, then express the total and itemised values in USD using a clearly stated approximate exchange-rate assumption. Scale estimates to the stated city, group size and budget. If exact city is unknown, state a reasonable broad assumption.
- If the user gives a total budget, keep every option within it unless explicitly showing a clearly-labelled stretch option.
- If a group size is known, include people_count and per_person = budget / people_count. Do not invent a group size.
- For emergencies, do not generate cheerful gift plans. If the user asks for a contribution calculation and has not supplied a hospital quote, do not fabricate a total medical bill. Explain what can be calculated now and ask for the actual estimate. If they provide a bill, calculate the requested fraction and split accurately.

PLAN GENERATION:
- Do not force plans into every turn. Chat naturally when the user is exploring, asking a factual question or thinking aloud.
- Offer structured plans when the user asks for ideas/options, asks you to prepare a plan, or the conversation has enough direction for useful options. Do not keep interrogating them first.
- When plans are appropriate, return 3 distinct, practical options. Each must have a real cost estimate and breakdown. Do not create three near-identical options just to fill a quota.
- Plans must include title, tagline, concept, activities, items, budget, currency, budget_min, budget_max, budget_breakdown, cost_note, people_count, per_person, timeline and why_it_fits. If a range or group size is unknown, use null for the relevant optional numeric field.
- Keep plans easy to compare. State assumptions rather than hiding them.
- When refining a plan, preserve details already agreed and change only what the user asks to change.
- Never claim to create a Moment, send invitations, collect money, contact people or book anything. That happens only after the organiser selects a plan and confirms in the app.

OUTPUT CONTRACT:
Return ONLY a valid JSON object with exactly these top-level fields:
{{"reply":"natural concise conversational message","ready":false,"plans":[],"questions":[]}}
When structured plans are appropriate, set ready=true and include 3 complete plans. Otherwise set ready=false and plans=[]. questions should normally be [] because any follow-up belongs naturally in reply. Do not put markdown fences around JSON.

Organiser name: {_planner_text(u['name'],100)}
Organiser profile city (use only if non-empty; never guess another city): {profile_city or 'Not provided'}
Conversation so far:
{convo}
Current planning context:
{context_text}
Latest organiser message:
{message}
''' 
    try:
        # Keep Pip responsive even if a provider stalls; this timeout is planner-only.
        result=await asyncio.wait_for(ai(prompt,as_json=True), timeout=22)
    except asyncio.TimeoutError:
        AI_ERR.update(ok=False, msg="Pip's AI provider took too long to respond. Please try once more.")
        result=None
    if not isinstance(result,dict):
        return {"ok":False,"ai":False,"reply":"I'm having a little trouble reaching my planning brain right now. Your ideas are safe — please try again in a moment.","ready":False,"plans":[],"questions":[],"error":AI_ERR.get("msg","")}
    reply=_planner_text(result.get("reply"),1800) or "I'm with you. Tell me what you're imagining, and we'll shape it together."
    ready=result.get("ready") is True; plans=[]
    raw=result.get("plans",[])
    if ready and isinstance(raw,list):
        for i,item in enumerate(raw[:4],1):
            p=_clean_planner_plan(item,i)
            if p: plans.append(p)
    if ready and len(plans)<3:
        ready=False; plans=[]
        reply += " I don't want to show you options with missing or unreliable cost breakdowns. I can keep helping conversationally, and we can narrow the estimate with one useful detail at a time."
    questions=result.get("questions",[])
    if not isinstance(questions,list): questions=[]
    return {"ok":True,"ai":bool(AI_ERR.get("ok")),"reply":reply,"ready":ready,"plans":plans,
      "questions":[_planner_text(q,250) for q in questions[:2] if _planner_text(q,250)],
      "error":"" if AI_ERR.get("ok") else AI_ERR.get("msg","")}

# ---------- End Pip AI planning companion ----------

TONES = {"warm": "warm and affectionate", "playful": "playful and witty", "heartfelt": "deeply heartfelt and sincere", "urgent": "urgent yet calm and caring"}
async def make_message(b, org, rec, sur, mid, same_person=False):
    link, key = f"{BASE}/#m{mid}", getattr(b, "tone", "warm")
    key = key if key in TONES else "warm"
    tone_text = TONES[key] if b.kind != "emergency" else "calm, caring and supportive. This is an EMERGENCY fund: never celebratory, never playful, no party emoji, speak like someone steady helping a friend through a hard moment"
    role_rule = (f"The organiser and recipient are the SAME PERSON ({rec}). Write in the organiser's first-person voice: they are asking their community for help for themselves. Never describe {rec} as a separate third person, and never say '{rec} is going through...'" if same_person else f"The organiser is {org}; the recipient/beneficiary is {rec}. Make it unmistakable that support is for {rec}, not for the contributors.")
    t = await ai(f"""You write fundraising messages people genuinely want to read, for a group chat. Tone: {tone_text}.
Rules: 70-110 words, plain text, at most 2 emoji, short paragraphs. Compose a brand-new message in your own words. {role_rule} Open with a specific detail from the facts, not a generic greeting. {'For an emergency, focus on the affected recipient/family and practical support; do not console contributors or imply that they are suffering.' if b.kind == 'emergency' else ''} {'This is a secret surprise; do not reveal it to the recipient.' if sur else ''}
Facts: kind={b.kind}; organiser={org}; recipient={rec}; occasion={b.occasion}; details={b.description}; who is who={b.context}; goal=${b.target:.0f}.
Say plainly that any amount is welcome and nobody is expected to give a fixed share. Finish with exactly this link: {link}""")
    if t: return t
    if b.kind == "emergency":
        opening = (f"I'm raising this fund for myself because {b.description.strip()}" if same_person and b.description.strip() else (f"I'm asking for support for myself during {b.occasion}." if same_person else f"{rec} and their family are facing a difficult situation: {b.description.strip() or b.occasion}."))
        return f"{opening} We are gathering ${b.target:.0f} to help with immediate needs. Any amount is welcome; there are no fixed shares and no pressure to give. Thank you for standing with us.\n\n{link}"
    op = {"warm": f"Something lovely is happening for {rec}, and I'd love for you to be part of it.", "playful": f"Breaking news: {rec} has a big one coming up ({b.occasion}) and we are not letting it pass quietly.",
          "heartfelt": f"{rec} has always shown up for us. Now it is our turn to show up.", "urgent": f"{rec} needs us right now, and this is a way we can help."}[key]
    return f"{op}\n\nWe are pooling together for {b.occasion}. Our goal is ${b.target:.0f}, but give whatever feels right, there are no fixed shares and every amount truly helps.{' Shh, it is a surprise!' if sur else ''}\n\n{link}"

# ---------- moments ----------
class NewMoment(BaseModel):
    recipient_id: int; occasion: str; target: float; kind: str = "occasion"; description: str = ""; context: str = ""
    surprise: bool = False; member_ids: list[int] = []; tone: str = "warm"

@app.post("/api/moments")
async def new_moment(b: NewMoment, u=Depends(me)):
    r = q("select * from users where id=?", (b.recipient_id,), one=True)
    if not r: raise HTTPException(404, "Recipient not found")
    if b.target <= 0 or not b.occasion.strip(): raise HTTPException(400, "Add an occasion and a target above zero")
    sur = int(b.surprise and r["id"] != u["id"])
    if sur and r["id"] in b.member_ids: raise HTTPException(400, "It's a surprise, so the recipient can't be in the group")
    mid = q("insert into moments(organiser_id,recipient_id,kind,occasion,description,context,surprise,target) values(?,?,?,?,?,?,?,?)",
            (u["id"], r["id"], b.kind, b.occasion, b.description, b.context, sur, b.target), w=True)
    ids = set(b.member_ids) - {u["id"]} - ({r["id"]} if sur else set())
    for uid in ids:
        q("insert into members values(?,?)", (mid, uid), w=True)
    if b.kind == "emergency":
        notify([u["id"]], "You created an emergency fund", mid, "🤍")
    else:
        notify([u["id"]], "You created a new moment", mid, "✨")
    notify(list(ids), f"{u['name']} created a new moment and added you as a contributor. You can join in once the group opens.", mid, "🤝")
    msg = await make_message(b, u["name"], r["name"], sur, mid, u["id"] == r["id"]); ok = AI_ERR["ok"]
    q("update moments set message=?, ai_ok=? where id=?", (msg, int(ok), mid), w=True)
    return {"id": mid, "ai": ok, "err": AI_ERR["msg"]}

@app.get("/api/moments")
def my_moments(u=Depends(me)):
    rows = q("""select distinct m.* from moments m left join members x on x.moment_id=m.id
        where m.organiser_id=? or (x.user_id=? and m.status!='draft') or (m.recipient_id=? and m.surprise=0 and m.status!='draft') order by m.id desc""", (u["id"],) * 3)
    return [{"id": m["id"], "occasion": m["occasion"], "kind": m["kind"], "status": m["status"], "target": m["target"], "collected": totals(m["id"])[1], "last": last_msg(m["id"]),
             "role": "Organiser" if m["organiser_id"] == u["id"] else "Recipient" if m["recipient_id"] == u["id"] else "Contributor"} for m in rows]

@app.get("/api/moments/{mid}")
def get_moment(mid: int, u=Depends(me)):
    m, org, rec = access(mid, u)
    cs, col, spent, left = totals(mid)
    names = defaultdict(lambda: "Deleted user", {r["id"]: r["name"] for r in q("select id,name from users")})
    d = dict(m)
    d.update(collected=col, spent=spent, leftover=left, is_organiser=org, is_recipient=m["recipient_id"] == u["id"], is_member=q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None,
             crew=[r["name"] for r in q("select u.name from members x join users u on u.id=x.user_id where x.moment_id=?", (mid,))],
             organiser_name=names[m["organiser_id"]], recipient_name=names[m["recipient_id"]],
             contributions=[{"name": names[c["user_id"]], "amount": c["a"], "share": round(c["a"] / col * 100, 1)} for c in cs],
             purchases=[dict(r) for r in q("select title,store,price,reasoning,status,link from purchases where moment_id=?", (mid,))],
             payouts=[{"name": names[r["user_id"]], "amount": r["amount"], "kind": r["kind"], "status": r["status"]} for r in q("select * from payouts where moment_id=?", (mid,))],
             preview=[{"name": names[k], "amount": v / 100} for k, v in split(round(left * 100), {c["user_id"]: c["a"] for c in cs}).items()] if left > 0 and cs else [])
    return d

class Msg(BaseModel): message: str

@app.put("/api/moments/{mid}/message")
def set_message(mid: int, b: Msg, u=Depends(me)):
    organiser_only(mid, u, ["draft", "active"]); q("update moments set message=? where id=?", (b.message, mid), w=True); return {"ok": True}

@app.post("/api/moments/{mid}/send")
async def send(mid: int, bg: BackgroundTasks, u=Depends(me)):
    organiser_only(mid, u, ["draft"]); q("update moments set status='active' where id=?", (mid,), w=True); launch(mid, u); bg.add_task(launch_ai, mid); return {"ok": True}

@app.post("/api/moments/{mid}/close")
def close(mid: int, u=Depends(me)):
    organiser_only(mid, u, ["active"])
    if totals(mid)[1] <= 0: raise HTTPException(400, "No contributions yet")
    say(mid, f"🔒|The pool is sealed at ${totals(mid)[1]:.2f}|Contributions are closed while the organiser picks the perfect next step.", "pay", u["id"])
    q("update moments set status='funded' where id=?", (mid,), w=True); return {"ok": True}

def _no_emergency_extras(m):
    if m["kind"] == "emergency": raise HTTPException(400, "Emergency funds keep it simple: send the money or return what's left.")

@app.post("/api/moments/{mid}/ask")
def ask_recipient(mid: int, u=Depends(me)):
    m = organiser_only(mid, u, ["funded"])
    _no_emergency_extras(m)
    if m["surprise"]: raise HTTPException(400, "Surprise mode: the recipient cannot be asked")
    say(mid, "💌|A question is on its way|The recipient is choosing between money and something special.", "pay", u["id"], skip={m["recipient_id"]})
    notify([m["recipient_id"]], "Your friends raised money for you. Would you like it as money or a gift?", mid, "💌")
    q("update moments set status='asking' where id=?", (mid,), w=True); return {"ok": True}

class Answer(BaseModel): choice: str; spec: str = ""

@app.post("/api/moments/{mid}/answer")
def answer(mid: int, b: Answer, u=Depends(me)):
    m, _, rec = access(mid, u)
    if not rec or m["status"] != "asking": raise HTTPException(403, "Nothing to answer right now")
    if b.choice not in ("money", "gift") or (b.choice == "gift" and not b.spec.strip()): raise HTTPException(400, "Say what you would like")
    say(mid, "🪄|The recipient has answered|" + ("They would love the money." if b.choice == "money" else "They'd love: " + b.spec[:80]), "pay", u["id"])
    q("update moments set status='answered', recipient_choice=?, recipient_spec=? where id=?", (b.choice, b.spec, mid), w=True); return {"ok": True}

@app.post("/api/moments/{mid}/payout")
async def payout_direct(mid: int, u=Depends(me)):
    m = organiser_only(mid, u, ["funded", "asking", "answered"])
    left = totals(mid)[3]
    if left <= 0: raise HTTPException(400, "Nothing left to send")
    r = q("select * from users where id=?", (m["recipient_id"],), one=True)
    await payouts(mid, [(r["id"], r["paypal_email"], left)], "recipient")
    say(mid, f"🎁|${left:.2f} is on its way to {r['name']}|{pay_line(m['kind'])}", "pay", u["id"], skip={r["id"]})
    if not m["surprise"]: notify([r["id"]], f"${left:.2f} just landed from your friends 🎁", mid, "🎁")
    q("update moments set status='done' where id=?", (mid,), w=True); return {"ok": True}

# ---------- AI product agent (free catalogs: DummyJSON + FakeStore) ----------
class Spec(BaseModel): spec: str; budget: float = 0; context: str = ""

from urllib.parse import quote
SERP = os.getenv("SERPAPI_KEY", "")
CHANNEL3 = os.getenv("CHANNEL3_API_KEY", "")
_cats = {}

async def _get(c, url, **kw):
    try: return (await c.get(url, **kw)).json()
    except Exception: return None

async def _categories(c):
    if not _cats.get("d"):
        d, f = await asyncio.gather(_get(c, "https://dummyjson.com/products/category-list"), _get(c, "https://fakestoreapi.com/products/categories"))
        _cats.update(d=d if isinstance(d, list) else [], f=f if isinstance(f, list) else [])
    return _cats

def _rate(p):  # ratings backed by many reviews count for more
    n = p.get("reviews", 0)
    return (p["rating"] * n + 4.0 * 15) / (n + 15) if n else p["rating"]

async def _channel3(c, query, max_price):
    """Live product search through Channel3 (https://docs.trychannel3.com). Same shape as the other sources; [] on any failure."""
    try:
        r = await c.post("https://api.trychannel3.com/v1/search", headers={"x-api-key": CHANNEL3, "Content-Type": "application/json"},
                         json={"query": query[:200], "limit": 20, "filters": {"price": {"max_price": round(float(max_price), 2)}}})
        data = r.json() if r.status_code == 200 else None
    except Exception: return []
    prods = data.get("products") if isinstance(data, dict) else data
    out = []
    for p in (prods if isinstance(prods, list) else []):
        try:
            offers = []
            for o in (p.get("offers") or []):
                pr = o.get("price") or {}
                v = float(pr.get("price") or 0)
                if v > 0 and (pr.get("currency") or "USD").upper() == "USD" and str(o.get("availability") or "InStock") not in ("OutOfStock", "SoldOut"): offers.append((v, o, pr))
            if not offers and isinstance(p.get("price"), dict) and p["price"].get("price"):
                v = float(p["price"]["price"]); offers.append((v, {"url": p.get("url", ""), "domain": ""}, p["price"]))
            ok = [x for x in offers if x[0] <= max_price + 0.001]
            if not ok: continue
            v, o, pr = min(ok, key=lambda x: x[0])
            old = float(pr.get("compare_at_price") or v)
            img = ""
            if isinstance(p.get("images"), list) and p["images"]: img = (p["images"][0] or {}).get("url", "") if isinstance(p["images"][0], dict) else str(p["images"][0])
            img = img or p.get("image_url", "")
            title = str(p.get("title", "")).strip()
            if not title: continue
            out.append({"store": o.get("domain") or p.get("brand_name") or "Online store", "title": title, "price": round(v, 2), "list_price": old, "discount": round((1 - v / old) * 100) if old > v else 0,
                        "rating": 0, "reviews": 0, "image": img, "link": o.get("url") or p.get("url", ""), "delivery": ""})
        except Exception: continue
    return out

async def find_products(spec, budget, context=""):
    """Real Google Shopping results when SERPAPI_KEY is set, otherwise free demo catalogs matched by AI-chosen categories."""
    out, seen, src, note = [], set(), "demo", ""
    def add(**p):
        if (p["store"], p["title"]) not in seen and p["price"] > 0: seen.add((p["store"], p["title"])); out.append({"reviews": 0, "link": "", "delivery": "", **p})
    async with httpx.AsyncClient(timeout=12) as c:
        cats = await _categories(c)
        plan = await ai("A friend group wants to buy: " + json.dumps(spec) + (f" (one part of this plan: {json.dumps(context)[:200]})" if context else "") + f" (budget ${budget:.0f}, US shoppers). Return a JSON object with keys: query (the best Google Shopping search query), alts (list of up to 2 alternative queries), "
                        f"dummy_categories (up to 2 slugs chosen only from {cats['d']}), fake_categories (up to 1 chosen only from {cats['f']}).", True)
        plan = plan if isinstance(plan, dict) else {}
        qs = [str(plan.get("query") or (f"{spec} {context}"[:100] if context else spec))] + [str(a) for a in (plan.get("alts") or [])][:2]
        if CHANNEL3:
            rs = await asyncio.gather(*[_channel3(c, qy, budget) for qy in qs[:2]])
            for r in rs:
                for p in r: add(**p)
            if out: src, note = "channel3", ""
        if SERP and not out:
            rs = await asyncio.gather(*[_get(c, "https://serpapi.com/search.json", params={"engine": "google_shopping", "q": qy, "api_key": SERP, "gl": "us", "hl": "en", "num": 20}) for qy in qs[:2]])
            for r in rs:
                if not isinstance(r, dict): note = note or "Google Shopping search failed"; continue
                if r.get("error"): note = "Google Shopping search failed: " + str(r["error"])[:120]; continue
                for p in r.get("shopping_results", []):
                    try:
                        pr = p.get("extracted_price") or 0; old = p.get("extracted_old_price") or pr
                        add(store=p.get("source", "Online store"), title=p.get("title", ""), price=pr, list_price=old, discount=round((1 - pr / old) * 100) if old > pr else 0,
                            rating=p.get("rating") or 0, reviews=p.get("reviews") or 0, image=p.get("thumbnail", ""), link=p.get("product_link") or p.get("link", ""), delivery=p.get("delivery", ""))
                    except Exception: pass
            if out: src, note = "google", ""
        if not out:
            def add_d(p):
                d = p.get("discountPercentage", 0)
                add(store="DummyJSON Store", title=p["title"], list_price=p["price"], discount=round(d), price=round(p["price"] * (1 - d / 100), 2), rating=p.get("rating", 0), reviews=len(p.get("reviews", [])), image=p.get("thumbnail", ""))
            kws = list(dict.fromkeys(qs + [w for w in spec.split() if len(w) > 3]))[:5]
            jobs = [_get(c, "https://dummyjson.com/products/search", params={"q": k, "limit": 10}) for k in kws]
            jobs += [_get(c, f"https://dummyjson.com/products/category/{cat}", params={"limit": 12}) for cat in (plan.get("dummy_categories") or [])[:2] if cat in cats["d"]]
            fjobs = [_get(c, "https://fakestoreapi.com/products/category/" + quote(cat)) for cat in (plan.get("fake_categories") or [])[:1] if cat in cats["f"]]
            res = await asyncio.gather(*jobs, *fjobs)
            for r in res[:len(jobs)]:
                for p in (r.get("products", []) if isinstance(r, dict) else []):
                    try: add_d(p)
                    except Exception: pass
            for r in res[len(jobs):]:
                for p in (r if isinstance(r, list) else []):
                    try: add(store="FakeStore", title=p["title"], list_price=p["price"], discount=0, price=p["price"], rating=p["rating"]["rate"], reviews=p["rating"]["count"], image=p["image"])
                    except Exception: pass
            note = note or "Showing free demo catalogs. Add a free SERPAPI_KEY to .env for live Google Shopping results."
    return out, src, note

@app.post("/api/moments/{mid}/search")
async def search(mid: int, b: Spec, u=Depends(me)):
    m = organiser_only(mid, u, ["funded", "asking", "answered"])
    _no_emergency_extras(m)
    left = totals(mid)[3]
    if left <= 0: raise HTTPException(400, "The pool is empty, so there is nothing left to spend.")
    if not b.spec.strip(): raise HTTPException(400, "Tell Pip what you would like to buy")
    budget = min(b.budget, left) if b.budget > 0 else left
    cands, src, note = await find_products(b.spec, budget, b.context.strip()[:200])
    base = {"budget": budget, "source": src, "note": note, "candidates": [], "pick": 0, "reasoning": "", "over": []}
    if not cands: return {**base, "note": (note + " " if note else "") + "Nothing matched that. Try different words."}
    inb = [p for p in cands if p["price"] <= budget]
    if not inb:
        base["over"] = sorted(cands, key=lambda p: p["price"])[:3]
        return {**base, "note": f"There are matches, but the cheapest starts at ${base['over'][0]['price']:.2f}, above your ${budget:.2f} budget."}
    for p in inb: p["pre"] = 0.6 * _rate(p) / 5 + 0.4 * (1 - p["price"] / budget)
    inb = inb[:10] if src == "channel3" else sorted(inb, key=lambda p: -p["pre"])[:10]  # Channel3 already returns its best matches first
    brief = [{"i": i, "store": p["store"], "title": p["title"], "price": p["price"], "discount_pct": p["discount"], "rating": p["rating"], "reviews": p["reviews"]} for i, p in enumerate(inb)]
    r = await ai("Wish: " + json.dumps(b.spec) + (f" (part of: {json.dumps(b.context.strip()[:200])})" if b.context.strip() else "") + f". Budget ${budget:.2f}. Options: " + json.dumps(brief) + ". Rate each option's RELEVANCE to the wish from 0 (unrelated) to 10 (exactly what was asked). "
                 "Then choose the single best overall: relevance first, then rating (trust ratings with many reviews), discount, and sensible use of the budget. "
                 'Return a JSON object {"relevance": [one integer per option, in order], "i": index of the best option, "reasoning": "two sentences citing real numbers and the store"}.', True)
    try:
        rel = [int(x) for x in r["relevance"]]; assert len(rel) == len(inb)
    except Exception:
        rel = [6 if any(w.lower()[:5] in p["title"].lower() for w in b.spec.split() if len(w) > 3) else 2 for p in inb]
    for p, x in zip(inb, rel): p["rel"] = x; p["score"] = round(0.45 * x / 10 + 0.3 * _rate(p) / 5 + 0.15 * (1 - p["price"] / budget) + 0.1 * min(p["discount"], 50) / 50, 3)
    good = [p for p in inb if p["rel"] >= 4]
    ranked = sorted(good or inb, key=lambda p: -p["score"])[:6 if good else 3]
    if not good:
        for p in ranked: p["weak"] = True
        note = "Nothing here is a close match for that. These are the nearest items" + (". Try different words." if src in ("google", "channel3") else ", because the free demo catalogs are small. A SERPAPI_KEY gives real store results.")
    pick, why = 0, ""
    try:
        ch = inb[int(r["i"])]
        if ch in ranked: pick, why = ranked.index(ch), str(r["reasoning"])
    except Exception: pass
    if not why: t = ranked[0]; why = f"Top pick: {t['title']} from {t['store']}, rated {t['rating']}/5 at ${t['price']:.2f}, ${budget - t['price']:.2f} under budget."
    return {**base, "candidates": ranked, "pick": pick, "reasoning": why, "note": note}

class Buy(BaseModel): title: str; store: str; price: float; reasoning: str = ""; link: str = ""

@app.post("/api/moments/{mid}/buy")
async def buy(mid: int, b: Buy, u=Depends(me)):
    m = organiser_only(mid, u, ["funded", "asking", "answered"])
    _no_emergency_extras(m)
    if b.price <= 0 or b.price > totals(mid)[3] + 0.001: raise HTTPException(400, "Price exceeds the funds left")
    try:
        oid, st = (await pp("POST", "/v2/checkout/orders", {"intent": "CAPTURE", "purchase_units": [{"reference_id": f"purchase-{mid}", "description": b.title[:120], "amount": {"currency_code": "USD", "value": f"{b.price:.2f}"}}]}))["id"], "order created"
    except HTTPException:
        if not FALLBACK: raise
        oid, st = "SIM-" + uuid.uuid4().hex[:8], "simulated"
    q("insert into purchases(moment_id,title,store,price,reasoning,order_id,status,link) values(?,?,?,?,?,?,?,?)", (mid, b.title, b.store, b.price, b.reasoning, oid, st, b.link), w=True)
    say(mid, f"🛍️|Bought: {b.title[:60]} (${b.price:.2f})|{pay_line(m['kind'])}", "pay", u["id"], skip={m["recipient_id"]})
    if not m["surprise"]: notify([m["recipient_id"]], f"A gift is on its way: {b.title[:60]}", mid, "🛍️")
    return {"ok": True}

@app.post("/api/moments/{mid}/refund")
async def refund(mid: int, u=Depends(me)):
    organiser_only(mid, u, ["funded", "asking", "answered"])
    cs, _, _, left = totals(mid)
    if left <= 0: raise HTTPException(400, "Nothing left to return")
    shares = split(round(left * 100), {c["user_id"]: c["a"] for c in cs})
    em = {r["id"]: r["paypal_email"] for r in q("select id,paypal_email from users")}
    await payouts(mid, [(k, em[k], v / 100) for k, v in shares.items() if v > 0], "refund")
    say(mid, f"🌿|${left:.2f} returned to contributors|Shared in proportion to what each person gave. Every cent found its way home.", "pay", u["id"])
    q("update moments set status='done' where id=?", (mid,), w=True); return {"ok": True}

# ---------- group chat + Pip (AI assistant) ----------
import random, re
from types import SimpleNamespace
PAY = ["Payment completed successfully."]
PAY_CALM = ["Your contribution was recorded successfully."]
def pay_line(kind): return random.choice(PAY_CALM if kind == "emergency" else PAY)

def audience(mid):
    m = q("select organiser_id, recipient_id, surprise from moments where id=?", (mid,), one=True)
    if not m: return []
    ids = [m["organiser_id"]] + [r["user_id"] for r in q("select user_id from members where moment_id=?", (mid,))]
    if not m["surprise"]: ids.append(m["recipient_id"])  # a surprise recipient hears nothing at all
    return list(dict.fromkeys(ids))

def notify(uids, body, mid=None, icon="🔔"):
    t = q("select occasion from moments where id=?", (mid,), one=True) if mid else None
    for x in set(uids): q("insert into notifs(user_id,moment_id,icon,title,body) values(?,?,?,?,?)", (x, mid, icon, t["occasion"] if t else "", body), w=True)

def say(mid, body, kind="system", uid=0, skip=()):
    q("insert into chat(moment_id,user_id,kind,body) values(?,?,?,?)", (mid, uid, kind, body), w=True)
    if kind == "pay":
        ic, title, _ = (body.split("|") + ["", "", ""])[:3]
        notify([x for x in audience(mid) if x != uid and x not in skip], title, mid, ic)

def last_msg(mid):
    r = q("select body,kind from chat where moment_id=? order by id desc limit 1", (mid,), one=True)
    return "" if not r else (r["body"].split("|")[1] if r["kind"] == "pay" else r["body"][:80])

def chat_access(mid, u):
    m, org, rec = access(mid, u)
    member = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
    if not (org or member or rec) or m["status"] == "draft":
        raise HTTPException(403, "The group chat opens once the organiser sends the message")
    return m

@app.get("/api/moments/{mid}/chat")
def chat(mid: int, after: int = 0, u=Depends(me)):
    try: chat_access(mid, u)
    except HTTPException: return []
    names = {r["id"]: r["name"] for r in q("select id,name from users")}
    return [{"id": r["id"], "kind": r["kind"], "body": r["body"], "uid": r["user_id"], "name": names.get(r["user_id"], ""), "ts": r["ts"]} for r in q("select * from chat where moment_id=? and id>? order by id", (mid, after))]

class Say(BaseModel): text: str

class ChatSuggestion(BaseModel): kind: str

@app.post("/api/moments/{mid}/chat/suggest")
async def chat_suggest(mid: int, b: ChatSuggestion, u=Depends(me)):
    m = chat_access(mid, u)
    org = m["organiser_id"] == u["id"]
    rec = m["recipient_id"] == u["id"] and not m["surprise"]
    member = q("select 1 from members where moment_id=? and user_id=?", (mid, u["id"]), one=True) is not None
    if b.kind == "thanks":
        if not (org or rec): raise HTTPException(403, "Only the organiser or recipient can use this thank-you message")
        prompt = f"Write a sincere, natural thank-you message (35-60 words) from {u['name']} to everyone who contributed to '{m['occasion']}'. This is an {'emergency fund' if m['kind']=='emergency' else 'group occasion fund'}. {'Keep it calm and heartfelt; acknowledge that people showed up during a difficult time, without sounding celebratory.' if m['kind']=='emergency' else 'Make it warm and appreciative.'} Do not claim a specific amount or promise anything. Output only the message."
    elif b.kind in ("congratulate", "support"):
        if not member or org or rec: raise HTTPException(403, "This option is for contributors")
        if m["kind"] == "emergency" and b.kind != "support": raise HTTPException(400, "Use a supportive message for an emergency fund")
        if m["kind"] != "emergency" and b.kind != "congratulate": raise HTTPException(400, "Use a congratulatory message for this occasion")
        prompt = f"Write a personal message (30-55 words) from {u['name']} to the recipient {q('select name from users where id=?',(m['recipient_id'],),one=True)['name']} for '{m['occasion']}'. {'This is an emergency. Be gentle, compassionate and practical; do not congratulate, minimize the situation, or console the contributor. Address the recipient directly.' if m['kind']=='emergency' else 'Congratulate the recipient warmly and naturally.'} Do not mention fundraising mechanics or invent facts. Output only the message."
    else:
        raise HTTPException(400, "Unknown message option")
    result = await ai(prompt)
    if not result:
        if b.kind == "thanks": result = "Thank you for showing up and helping us through this. Your kindness means more than words can say. We are grateful to have you beside us."
        elif b.kind == "support": result = "I’m thinking of you and your family. I hope you have the support and space you need right now. Please know you are not facing this alone."
        else: result = f"Congratulations on {m['occasion']}! I’m so happy for you and hope this moment brings you plenty of joy."
    return {"message": result.strip()[:700], "ai": AI_ERR["ok"]}

@app.post("/api/moments/{mid}/chat")
async def post_chat(mid: int, b: Say, bg: BackgroundTasks, u=Depends(me)):
    chat_access(mid, u); t = b.text.strip()[:500]
    if not t: raise HTTPException(400, "Say something first")
    say(mid, t, "text", u["id"])
    if re.match(r"@pip\b", t, re.I): bg.add_task(pip_reply, mid, u["name"], t[4:])  # Pip answers a moment later, sending never waits on the AI
    return {"ok": True}

async def pip_reply(mid, who, ask):
    try:
        m = q("select * from moments where id=?", (mid,), one=True)
        if not m: return
        _, col, _, left = totals(mid)
        r = await ai(f"You are Pip, a warm, witty assistant inside a group chat raising money for '{m['occasion']}' (details: {m['description']} {m['context']}). Goal ${m['target']:.0f}, raised ${col:.2f}. {'It is a SURPRISE: never hint to the recipient.' if m['surprise'] else ''} Answer {who} in max 60 words, specific and useful: {ask}")
        say(mid, r or "Pip is catching a nap (add a Gemini key and I'll wake up). Meanwhile: every amount counts, and the ring shows how close you are.", "ai")
    except Exception as e: print("[Pip]", e)

def launch(mid, u):
    m = q("select * from moments where id=?", (mid,), one=True)
    say(mid, m["message"], "text", u["id"])
    notify([r["user_id"] for r in q("select user_id from members where moment_id=?", (mid,))], f"{u['name']} invited you to give to {m['occasion']}", mid, "💌")
    if not m["surprise"]:
        icon = "🤍" if m["kind"] == "emergency" else "💝"
        title = (
            f"{u['name']} started an emergency fund for you: {m['occasion']}"
            if m["kind"] == "emergency"
            else f"{u['name']} started a moment for you: {m['occasion']}"
        )
        notify([m["recipient_id"]], title, mid, icon)
async def launch_ai(mid):
    try:
        m = q("select * from moments where id=?", (mid,), one=True)
        if not m: return
        emer = m["kind"] == "emergency"
        rec = q("select name from users where id=?", (m["recipient_id"],), one=True)["name"]
        w = await ai(f"You are Pip in a real friends' group chat. Write ONE natural welcome message, maximum 22 words, for '{m['occasion']}'. Sound like a thoughtful friend, not an advertisement or app tutorial. Mention that contributions are optional and any amount is welcome. Do not say 'Hello, I'm Pip', do not use a sales pitch, and do not repeat the occasion as an intro. {'This is an emergency fund: be calm and respectful, with no celebration language or party emoji.' if emer else 'A single gentle celebratory touch is fine, but do not overdo emojis.'} {'Briefly remind the group to keep it a surprise.' if m['surprise'] else ''} Output plain text only, no JSON, braces, member list or headings.")
        fallback = ("Welcome, everyone. Give only what feels comfortable; every contribution helps, and there are no fixed shares." if emer else "Welcome, everyone. Chip in only if you feel like it — any amount is welcome, and every contribution will show here.")
        welcome = (w or fallback).strip().strip('`')
        if welcome.startswith('{') or welcome.startswith('[') or '"members"' in welcome.lower():
            welcome = fallback
        say(mid, welcome[:420], "ai")
        if emer:
            support = await ai(f"Write one short, gentle message (maximum 20 words) addressed directly to {rec}, the person affected by this emergency. No assumptions about recovery. Plain text only.")
            if support and not support.strip().startswith(('{', '[')):
                say(mid, support.strip()[:240], "ai")
    except Exception as e: print("[Pip welcome]", e)

async def celebrate(mid, u, amt, to_org=False, bg=None):
    m = q("select * from moments where id=?", (mid,), one=True); col = totals(mid)[1]
    payment_status = "Sent to the organiser's PayPal account." if to_org else "Payment completed successfully through MomentPay's PayPal account."
    say(mid, f"💸|{u['name']} contributed ${amt:.2f}|{payment_status}", "pay", u['id'])
    notify([u["id"]], f"You contributed ${amt:.2f}", mid, "💸")
    for th, word in ((0.5, "halfway"), (1, "fully funded")):
        if (col - amt) / m["target"] < th <= col / m["target"]:
            if bg is not None: bg.add_task(cheer, mid, th, word, col, m["target"], m["occasion"], m["kind"])
            else: await cheer(mid, th, word, col, m["target"], m["occasion"], m["kind"])

async def cheer(mid, th, word, col, target, occasion, kind="occasion"):
    try:
        if kind == "emergency":
            t = await ai(f"Write one calm, caring sentence (max 25 words, NOT celebratory, no party emoji) for a group chat: an emergency fund for '{occasion}' just reached {word} (${col:.0f} of ${target:.0f}). Name no individual.")
            say(mid, t or ("Halfway to the goal. Thank you for standing with them." if th < 1 else "The goal has been reached. The organiser can take it from here."), "ai")
        else:
            t = await ai(f"Write one joyful sentence (max 25 words) for a group chat: the fund for '{occasion}' just became {word} (${col:.0f} of ${target:.0f}). Name no individual.")
            say(mid, t or ("Halfway there! The tide is turning. 🌊" if th < 1 else "We did it. The goal is met, and the organiser can take it from here. 🎉"), "ai")
    except Exception as e: print("[Pip cheer]", e)

class Regen(BaseModel): tone: str = "warm"

@app.post("/api/moments/{mid}/regenerate")
async def regen(mid: int, b: Regen, u=Depends(me)):
    m = organiser_only(mid, u, ["draft"])
    n = {r["id"]: r["name"] for r in q("select id,name from users")}
    s_ = SimpleNamespace(kind=m["kind"], occasion=m["occasion"], description=m["description"], context=m["context"], target=m["target"], tone=b.tone)
    t = await make_message(s_, n[m["organiser_id"]], n[m["recipient_id"]], m["surprise"], mid, m["organiser_id"] == m["recipient_id"])
    ok = AI_ERR["ok"]; q("update moments set message=?, ai_ok=? where id=?", (t, int(ok), mid), w=True); return {"message": t, "ai": ok, "err": AI_ERR["msg"]}

@app.get("/api/moments/{mid}/ideas")
async def ideas(mid: int, u=Depends(me)):
    m = organiser_only(mid, u, ["funded", "asking", "answered"])
    _no_emergency_extras(m)
    r = await ai(f"Gift for '{m['occasion']}'. Context: {m['description']} {m['context']}. Budget ${totals(mid)[3]:.0f}. Suggest 5 concrete everyday product search phrases (1-3 words each) that suit the person. Return a JSON list of strings.", True)
    return [x for x in r if isinstance(x, str)][:5] if isinstance(r, list) else ["backpack", "watch", "headphones", "lamp", "kitchen"]

def _money_parse(txt):
    """'$1,200.00', 'US$1.200,50' or '35' -> float (None if there is no number)."""
    m = re.findall(r"\d[\d.,\s]*", txt or "")
    if not m: return None
    n = m[-1].strip().replace(" ", "")
    if "," in n and "." in n: n = n.replace(",", "") if n.rfind(".") > n.rfind(",") else n.replace(".", "").replace(",", ".")
    elif "," in n: n = n.replace(",", ".") if len(n.rsplit(",", 1)[1]) in (1, 2) else n.replace(",", "")
    try: return float(n)
    except ValueError: return None

@app.get("/api/moments/{mid}/plan-items")
async def plan_items(mid: int, u=Depends(me)):
    """The things decided with Pip when the moment was created, with the budget split from that plan."""
    m = organiser_only(mid, u, ["funded", "asking", "answered"])
    _no_emergency_extras(m)
    left = totals(mid)[3]
    items, on = [], False
    for line in (m["context"] or "").split("\n"):
        if line.lower().startswith("estimated budget breakdown"): on = True; continue
        if not on: continue
        if not line.strip() or ":" not in line: break
        label, amt = line.rsplit(":", 1)
        v = _money_parse(amt)
        if label.strip() and v and v > 0: items.append({"label": label.strip()[:80], "planned": round(v, 2)})
    if items:
        tot = sum(i["planned"] for i in items); k = min(1.0, left / tot) if tot > 0 else 1.0
        for i in items: i["budget"] = round(min(left, i["planned"] * k), 2)
    else:
        for l in (m["description"] or "").split("\n"):
            if l.startswith("Things to arrange:"):
                for t in l.split(":", 1)[1].split(";"):
                    if t.strip(): items.append({"label": t.strip()[:80], "planned": 0, "budget": round(left, 2)})
    return {"items": items[:12], "plan": m["occasion"]}

_AIST = {"t": 0.0, "r": None}
@app.get("/api/ai/status")
async def ai_status():
    if _AIST["r"] and time.time() - _AIST["t"] < (300 if _AIST["r"]["ok"] else 30): return _AIST["r"]  # not a live AI call on every page load
    r = await ai("Reply with exactly one word: ready")
    res = {"ok": bool(r), "error": "" if r else AI_ERR["msg"]}
    _AIST.update(t=time.time(), r=res); return res

def _purge(mid):
    for t in ("chat", "members", "contributions", "purchases", "payouts", "notifs"): q(f"delete from {t} where moment_id=?", (mid,), w=True)
    q("delete from moments where id=?", (mid,), w=True)

def _notify_removed(m, u):
    ids = [r["user_id"] for r in q("select user_id from members where moment_id=?", (m["id"],))]
    if not m["surprise"] and m["status"] != "draft": ids.append(m["recipient_id"])
    notify([x for x in ids if x != u["id"]], f"{u['name']} removed the moment '{m['occasion']}'", None, "🗑")

@app.delete("/api/moments/{mid}")
def delete_moment(mid: int, u=Depends(me)):
    m, org, _ = access(mid, u)
    if not org: raise HTTPException(403, "Only the organiser can delete this moment")
    if totals(mid)[3] > 0.005: raise HTTPException(400, "There is still money in the pool. Send it on or return it to contributors first.")
    _notify_removed(m, u); _purge(mid); return {"ok": True}

@app.get("/api/ai/check")
async def ai_check():
    t = await ai("Reply with the single word: ready")
    return {"ok": bool(t), "reply": t, "last_error": AI_ERR["msg"], "gemini_key": bool(GKEY), "groq_key": bool(GROQ_KEY), "search": "google_shopping" if SERP else "demo_catalog"}

@app.get("/api/notifications")
def notifications(u=Depends(me)):
    rows = q("select * from notifs where user_id=? order by id desc limit 60", (u["id"],))
    return {"items": [dict(r) for r in rows], "unread": q("select count(*) c from notifs where user_id=? and seen=0", (u["id"],), one=True)["c"]}

@app.post("/api/notifications/read")
def notifications_read(u=Depends(me)):
    q("update notifs set seen=1 where user_id=?", (u["id"],), w=True); return {"ok": True}

@app.get("/api/pulse")
def pulse(moment: int = 0, after: int = 0, u=Depends(me)):
    """One tiny call replaces the separate chat, moment and notification polls."""
    n = q("select max(id) top, sum(seen=0) unread from notifs where user_id=?", (u["id"],), one=True)
    out = {"top": n["top"] or 0, "unread": n["unread"] or 0, "chat": [], "sig": None}
    if moment:
        try:
            m, _, _ = access(moment, u)
            _, col, _, left = totals(moment)
            out["sig"] = [m["status"], col, left, m["recipient_choice"], q("select count(*) c from purchases where moment_id=?", (moment,), one=True)["c"], q("select count(*) c from payouts where moment_id=?", (moment,), one=True)["c"]]
            out["chat"] = chat(moment, after, u)
        except HTTPException: out["gone"] = True
    return out

class DelAcct(BaseModel): password: str

@app.post("/api/profile/delete")
def delete_account(b: DelAcct, u=Depends(me)):
    if h(b.password) != u["pw"]: raise HTTPException(400, "That password is not right")
    uid = u["id"]
    rows = q("select * from moments where organiser_id=? or recipient_id=? or id in (select moment_id from contributions where user_id=?)", (uid, uid, uid))
    busy = [m["occasion"] for m in rows if totals(m["id"])[3] > 0.005]
    if busy: raise HTTPException(400, "Money is still in play in: " + ", ".join(busy[:4]) + ". Send it on or return it first, then delete your account.")
    for m in rows:
        if m["organiser_id"] == uid: _notify_removed(m, u); _purge(m["id"])
    q("delete from members where user_id=?", (uid,), w=True); q("delete from notifs where user_id=?", (uid,), w=True); q("delete from users where id=?", (uid,), w=True)
    return {"ok": True}

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True))
