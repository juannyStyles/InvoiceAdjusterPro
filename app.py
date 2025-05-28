from flask import Flask, request, session, redirect, url_for, jsonify
import os, json
from requests_oauthlib import OAuth2Session
from update_invoice_generic import main as do_update

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

CLIENT_ID     = os.environ["QBO_CLIENT_ID"]
CLIENT_SECRET = os.environ["QBO_CLIENT_SECRET"]
REALM_ID      = os.environ["QBO_REALM_ID"]
REDIRECT_URI  = os.environ["OAUTH_REDIRECT_URI"]
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

AUTH_BASE     = "https://appcenter.intuit.com/connect/oauth2"
SCOPE         = ["com.intuit.quickbooks.accounting"]

@app.route("/launch")
def launch():
    oauth = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPE)
    auth_url, state = oauth.authorization_url(AUTH_BASE)
    session["oauth_state"] = state
    return redirect(auth_url)

@app.route("/connect")
def connect():
    oauth = OAuth2Session(CLIENT_ID, state=session["oauth_state"],
                          redirect_uri=REDIRECT_URI)
    token = oauth.fetch_token(
        token_url=TOKEN_URL,
        client_secret=CLIENT_SECRET,
        authorization_response=request.url
    )
    # For debugging, temporarily return the token directly
    return jsonify(token)
    
    # Persist to disk for update_invoice_generic to pick up
    open("qbo_token.json","w").write(json.dumps(token))
    return "✅ Connected to QuickBooks!"

@app.route("/update", methods=["POST"])
def update():
    cfg = request.get_json(force=True)
    try:
        result = do_update(cfg)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status":"error","error": str(e)}), 400

@app.route("/")
def index():
    return """
    <h1>Invoice Adjuster</h1>
    <p><a href="/launch">Connect your QuickBooks</a></p>
    <p>POST JSON to /update to run parse updates.</p>
    """

if __name__=="__main__":
    # Local debug
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=True)
