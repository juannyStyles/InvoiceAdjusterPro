#!/usr/bin/env python3
import os, json, logging
from flask import Flask, request, session, redirect, jsonify, make_response
from requests_oauthlib import OAuth2Session

# your helpers:
from update_invoice_generic import (
    get_session,
    find_invoice_id,
    API_BASE,
    REALM_ID,
    TOKEN_FILE,
    main as update_main
)

# ─── FLASK SETUP ────────────────────────────────────────────────
app = Flask(__name__)
# required so session["oauth_state"] works
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

logging.basicConfig(level=logging.INFO)

CLIENT_ID     = os.environ["QBO_CLIENT_ID"]
CLIENT_SECRET = os.environ["QBO_CLIENT_SECRET"]
REDIRECT_URI  = os.environ["QBO_REDIRECT_URI"]      # must match QuickBooks console
AUTH_BASE     = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE         = ["com.intuit.quickbooks.accounting"]

# ─── ROUTES ────────────────────────────────────────────────────
@app.route("/")
def index():
    return """
    <h1>Invoice Adjuster Pro</h1>
    <p><a href="/launch">Connect to QuickBooks</a></p>
    <p>POST JSON to <code>/update</code> to patch invoices, or GET <code>/download_pdf/&lt;DocNumber&gt;</code>.</p>
    """

@app.route("/launch")
def launch():
    oauth = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPE)
    auth_url, state = oauth.authorization_url(AUTH_BASE)
    session["oauth_state"] = state
    return redirect(auth_url)

@app.route("/connect")
def connect():
    saved = session.get("oauth_state")
    if not saved:
        return "No OAuth session found—start at /launch", 400

    oauth = OAuth2Session(
        CLIENT_ID,
        state=saved,
        redirect_uri=REDIRECT_URI
    )
    token = oauth.fetch_token(
        token_url=TOKEN_URL,
        client_secret=CLIENT_SECRET,
        authorization_response=request.url
    )

    # write to the same TOKEN_FILE your loader expects
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)

    return jsonify({"status":"connected"})

@app.route("/update", methods=["POST"])
def update():
    cfg = request.get_json(force=True)
    try:
        result = update_main(cfg)
        return jsonify(result)
    except Exception as e:
        logging.exception("Update failed")
        return jsonify({"status":"error", "error": str(e)}), 400

@app.route("/download_pdf/<docnum>")
def download_pdf_endpoint(docnum):
    sess = get_session()
    inv_id, _ = find_invoice_id(sess, docnum)
    pdf_url = f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}/pdf"
    r = sess.get(pdf_url, headers={"Accept":"application/pdf"})
    r.raise_for_status()

    resp = make_response(r.content)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename={docnum}.pdf"
    return resp

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )

