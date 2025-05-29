#!/usr/bin/env python3
from flask import Flask, request, session, redirect, jsonify, make_response
import os, json
from requests_oauthlib import OAuth2Session

# import QBO helper routines from your existing module
from update_invoice_generic import (
    get_session,
    find_invoice_id,
    API_BASE,
    REALM_ID,
)

app = Flask(__name__)
app.secret_key    = os.environ["FLASK_SECRET_KEY"]
CLIENT_ID         = os.environ["QBO_CLIENT_ID"]
CLIENT_SECRET     = os.environ["QBO_CLIENT_SECRET"]
REDIRECT_URI      = os.environ["OAUTH_REDIRECT_URI"]
TOKEN_URL         = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
AUTH_BASE         = "https://appcenter.intuit.com/connect/oauth2"
SCOPE             = ["com.intuit.quickbooks.accounting"]

@app.route("/launch")
def launch():
    oauth = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPE)
    auth_url, state = oauth.authorization_url(AUTH_BASE)
    session["oauth_state"] = state
    return redirect(auth_url)

@app.route("/connect")
def connect():
    oauth = OAuth2Session(
        CLIENT_ID,
        state=session["oauth_state"],
        redirect_uri=REDIRECT_URI
    )
    token = oauth.fetch_token(
        token_url=TOKEN_URL,
        client_secret=CLIENT_SECRET,
        authorization_response=request.url
    )
    # persist for update_invoice_generic to pick up
    with open("qbo_token.json","w") as f:
        json.dump(token, f)
    return "✅ Connected to QuickBooks!"

@app.route("/update", methods=["POST"])
def update():
    """
    Expects JSON like:
      {
        "DocNumber": "1069",
        "Updates": { "TxnDate":"2025-09-30", ... },
        "CustomFields": { "Crew #":"42", ... },
        "SaveDir": "/some/local/path"       # optional
      }
    """
    cfg = request.get_json(force=True)
    try:
        result = __import__('update_invoice_generic').main(cfg)
        return jsonify(result)
    except Exception as e:
        return jsonify({ "status":"error", "error": str(e) }), 400

@app.route("/download_pdf/<docnum>")
def download_pdf_endpoint(docnum):
    """
    Fetch the raw PDF bytes for invoice `docnum` and stream them back.
    """
    sess     = get_session()
    inv_id, _ = find_invoice_id(sess, docnum)
    r = sess.get(
        f"{API_BASE}/v3/company/{REALM_ID}/invoice/{inv_id}/pdf",
        headers={ "Accept":"application/pdf" }
    )
    r.raise_for_status()

    resp = make_response(r.content)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename={docnum}.pdf"
    return resp

@app.route("/")
def index():
    return """
    <h1>Invoice Adjuster</h1>
    <p><a href="/launch">Connect your QuickBooks</a></p>
    <p>POST your JSON to <code>/update</code> to patch invoices.<br>
       GET <code>/download_pdf/&lt;DocNumber&gt;</code> to retrieve the PDF.</p>
    """

if __name__=="__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )

