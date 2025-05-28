#!/usr/bin/env python3
import os, sys, json, time, re
from datetime import date, datetime
import requests
from requests_oauthlib import OAuth2Session

# ─── CONFIG ────────────────────────────────────────────────────
USE_SANDBOX   = True
API_BASE      = ("https://sandbox-quickbooks.api.intuit.com"
                 if USE_SANDBOX else
                 "https://quickbooks.api.intuit.com")
MINOR_VERSION = 75

SCRIPT_DIR    = os.path.dirname(__file__)
TOKEN_FILE    = os.path.join(SCRIPT_DIR, "qbo_token.json")
CLIENT_ID     = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("QBO_REFRESH_TOKEN")
REALM_ID      = os.getenv("QBO_REALM_ID")
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

# ─── AUTH ──────────────────────────────────────────────────────
def load_token():
    if os.path.isfile(TOKEN_FILE):
        return json.load(open(TOKEN_FILE))
    return {"refresh_token":REFRESH_TOKEN,"access_token":"","expires_at":0,"token_type":"bearer"}

def save_token(tok):
    with open(TOKEN_FILE,"w") as f:
        json.dump(tok,f)

def get_session():
    tok = load_token()
    extra = {"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET}
    sess = OAuth2Session(
        CLIENT_ID, token=tok,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs=extra,
        token_updater=save_token
    )
    sess.headers.update({"Accept-Encoding": "identity"})
    if tok.get("expires_at",0) <= time.time():
        sess.refresh_token(TOKEN_URL, **extra)
    return sess

# ─── QBO HELPERS ───────────────────────────────────────────────
def find_invoice_id(sess, docnum):
    sql = f"select Id,SyncToken from Invoice where DocNumber='{docnum}'"
    r   = sess.get(f"{API_BASE}/v3/company/{REALM_ID}/query",
                   params={"query":sql},
                   headers={"Accept":"application/json"})
    r.raise_for_status()
    invs = r.json().get("QueryResponse",{}).get("Invoice",[])
    if not invs:
        raise ValueError(f"No invoice '{docnum}'")
    return invs[0]["Id"], invs[0]["SyncToken"]

def download_pdf(sess, inv_id, dest):
    r = sess.get(f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}/pdf",
                 headers={"Accept":"application/pdf"})
    r.raise_for_status()
    open(dest,"wb").write(r.content)

def get_invoice(sess, inv_id):
    r = sess.get(
        f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}",
        params={"minorversion":MINOR_VERSION},
        headers={"Accept":"application/json"}
    )
    r.raise_for_status()
    return r.json()["Invoice"]

def get_custom_defs(sess):
    r = sess.get(f"{API_BASE}/v3/company/{REALM_ID}/preferences",
                 headers={"Accept":"application/json"})
    r.raise_for_status()
    prefs = r.json().get("Preferences",{})
    out = {}
    for blk in prefs.get("SalesFormsPrefs",{}).get("CustomField",[]):
        for cf in blk.get("CustomField",[]):
            nameKey = cf.get("Name","")
            if not nameKey.startswith("SalesFormsPrefs.SalesCustomName"): continue
            display = cf.get("StringValue","").strip()
            if not display: continue
            m = re.search(r"(\d+)$", nameKey)
            if not m: continue
            out[display] = {"DefinitionId":m.group(1),"Type":cf.get("Type")}
    # for debug
    open(os.path.join(SCRIPT_DIR,"last_defs.json"),"w").write(json.dumps(out,indent=2))
    print("[DEBUG] defs → last_defs.json",file=sys.stderr)
    return out

# ─── SPARSE UPDATE ─────────────────────────────────────────────
def sparse_update(sess, inv_id, sync, updates, customs):
    inv         = get_invoice(sess,inv_id)
    defs        = get_custom_defs(sess)

    cf_payload=[]
    for name,val in customs.items():
        d = defs.get(name)
        if not d:
            print(f"[DEBUG] skip unknown “{name}”",file=sys.stderr)
            continue
        entry={"DefinitionId":d["DefinitionId"],"Name":name,"Type":d["Type"]}
        if d["Type"]=="DateType":
            dt=datetime.strptime(val,"%m/%d/%Y").date()
            entry["DateValue"]=dt.strftime("%Y-%m-%d")
        elif d["Type"]=="StringType":
            entry["StringValue"]=val
        else:
            entry["NumberValue"]=val
        cf_payload.append(entry)

    inv_body = {
        "Id":        inv_id,
        "SyncToken": sync,
        "sparse":    True,
        **updates
    }
    if cf_payload:
        inv_body["CustomField"] = cf_payload

    open(os.path.join(SCRIPT_DIR,"last_payload.json"),"w").write(json.dumps(inv_body,indent=2))
    print("[DEBUG] payload → last_payload.json",file=sys.stderr)

    url = (f"{API_BASE}/v3/company/{REALM_ID}"
           f"/invoice?operation=update&minorversion={MINOR_VERSION}")
    r = sess.post(url, json=inv_body,
                  headers={"Content-Type":"application/json",
                           "Accept":"application/json",
                           "Accept-Encoding":"identity"})
    if not r.ok:
        print(f"[DEBUG] QBO {r.status_code}: {r.text}", file=sys.stderr)
    r.raise_for_status()

# ─── PUBLIC API ────────────────────────────────────────────────
def main(cfg: dict) -> dict:
    """
    cfg = {
      "DocNumber": "...",
      "Updates": { "TxnDate":"YYYY-MM-DD", ... },
      "CustomFields": { "Foo":"val", ... },
      "SaveDir": "/some/path"           # optional
    }
    """
    doc     = cfg["DocNumber"]
    updates = cfg.get("Updates",{})
    customs = cfg.get("CustomFields",{})
    save_dir= cfg.get("SaveDir","")

    sess     = get_session()
    inv_id,sync = find_invoice_id(sess,doc)

    if save_dir:
        inv = get_invoice(sess,inv_id)
        old = datetime.strptime(inv["TxnDate"],"%Y-%m-%d").date()
        fn  = f"{doc} - {old} - moved_{date.today()}.pdf"
        os.makedirs(save_dir,exist_ok=True)
        download_pdf(sess,inv_id,os.path.join(save_dir,fn))

    sparse_update(sess,inv_id,sync,updates,customs)
    return {"status":"ok","doc":doc}

# ─── CLI ENTRYPOINT ────────────────────────────────────────────
if __name__=="__main__":
    try:
        if len(sys.argv)!=2:
            raise RuntimeError("Usage: update_invoice_generic.py <config.json>")
        cfg = json.load(open(sys.argv[1]))
        out = main(cfg)
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"status":"error","error":str(e)}))
        sys.exit(1)

