#!/usr/bin/env python
import os
import sys
import json
import time
import requests
from datetime import datetime, date
from requests_oauthlib import OAuth2Session

# ─── Configuration ─────────────────────────────────────────────────────────────
USE_SANDBOX   = True
API_BASE      = "https://sandbox-quickbooks.api.intuit.com" if USE_SANDBOX \
                  else "https://quickbooks.api.intuit.com"
MINOR_VERSION = 75

# Token store alongside this script
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, 'qbo_token.json')

CLIENT_ID         = os.getenv('QBO_CLIENT_ID')
CLIENT_SECRET     = os.getenv('QBO_CLIENT_SECRET')
REFRESH_TOKEN_ENV = os.getenv('QBO_REFRESH_TOKEN')
REALM_ID          = os.getenv('QBO_REALM_ID')
TOKEN_URL         = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'

# ─── Token Store ────────────────────────────────────────────────────────────────
def load_token():
    if os.path.isfile(TOKEN_FILE):
        return json.load(open(TOKEN_FILE))
    return {
        'refresh_token': REFRESH_TOKEN_ENV,
        'access_token':   '',
        'expires_at':     0,
        'token_type':     'bearer'
    }

def save_token(token):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token, f)

# ─── OAuth Session ──────────────────────────────────────────────────────────────
def get_session():
    token = load_token()
    extra = {'client_id':CLIENT_ID, 'client_secret':CLIENT_SECRET}
    sess = OAuth2Session(
        CLIENT_ID,
        token=token,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs=extra,
        token_updater=save_token
    )
    if token.get('expires_at',0) <= time.time():
        sess.refresh_token(TOKEN_URL, **extra)
    return sess

# ─── QBO Helpers ───────────────────────────────────────────────────────────────
def find_invoice_id(sess, docnum):
    q   = f"select Id,SyncToken from Invoice where DocNumber = '{docnum}'"
    url = f"{API_BASE}/v3/company/{REALM_ID}/query"
    r   = sess.get(url, params={'query':q}, headers={'Accept':'application/json'})
    r.raise_for_status()
    invs = r.json().get('QueryResponse', {}).get('Invoice',[])
    if not invs:
        raise ValueError(f"No invoice with DocNumber='{docnum}' found")
    return invs[0]['Id'], invs[0]['SyncToken']

def download_pdf(sess, inv_id, dest):
    url = f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}/pdf"
    r   = sess.get(url, headers={'Accept':'application/pdf'})
    r.raise_for_status()
    with open(dest, 'wb') as f:
        f.write(r.content)

def update_date_sparse(sess, inv_id, sync_token, new_date):
    url = (
        f"{API_BASE}/v3/company/{REALM_ID}"
        f"/invoice?operation=update&minorversion={MINOR_VERSION}"
    )
    payload = {
        "Id":        inv_id,
        "SyncToken": sync_token,
        "sparse":    True,
        "TxnDate":   new_date
    }
    headers = {'Content-Type':'application/json','Accept':'application/json'}
    r = sess.post(url, json=payload, headers=headers)
    r.raise_for_status()

# ─── Main CLI ───────────────────────────────────────────────────────────────────
def main(docnum, new_date, save_dir):
    sess = get_session()

    # 1) Lookup internal Id & SyncToken
    inv_id, sync = find_invoice_id(sess, docnum)

    # 2) Fetch original TxnDate for naming
    inv_json = sess.get(
        f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}",
        headers={'Accept':'application/json'}
    ).json()['Invoice']
    orig = inv_json['TxnDate']  # e.g. "2025-02-01"

    # format old date & today
    old_dt     = datetime.strptime(orig, '%Y-%m-%d').date()
    old_fmt    = old_dt.strftime('%m.%d.%Y')
    today_fmt  = date.today().strftime('%m.%d.%Y')

    # build filename
    filename = f"{docnum} - {old_fmt} - Moved on {today_fmt}.pdf"
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)

    # 3) download & 4) update
    download_pdf(sess, inv_id, filepath)
    update_date_sparse(sess, inv_id, sync, new_date)

    # 5) status back to Excel
    print(f"OK|{docnum}: saved {filename}, date-> {new_date}")

if __name__ == '__main__':
    try:
        if len(sys.argv) != 4:
            raise ValueError("Usage: update_invoice.py <DocNumber> <YYYY-MM-DD> <SaveDir>")
        main(*sys.argv[1:])
    except Exception as e:
        idf = sys.argv[1] if len(sys.argv)>1 else "?"
        print(f"ERROR|{idf}: {e}")
        sys.exit(1)
