import os
import requests
import sqlite3
import json
from datetime import datetime, timezone
import time
import webbrowser
import http.server
import socketserver
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv
import mimetypes
import requests

# Load environment variables
load_dotenv()

# API configurations
ZOHO_API_BASE = "https://www.zohoapis.in/crm/v7"
HUBSPOT_UPLOAD_URL = "https://api.hubspot.com/files/v3/files"
HUBSPOT_DEALS_API = "https://api.hubspot.com/crm/v3/objects/deals"
HUBSPOT_NOTES_API = "https://api.hubspot.com/crm/v3/objects/notes"
ZOHO_TOKEN_URL = "https://accounts.zoho.in/oauth/v2/token"
ZOHO_AUTH_URL = "https://accounts.zoho.in/oauth/v2/auth"
HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubspot.com/oauth/v1/token"
HUBSPOT_FOLDERS_API = "https://api.hubspot.com/files/v3/folders"

# OAuth configurations
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8000"
ZOHO_SCOPE = "ZohoCRM.modules.ALL,ZohoCRM.bulk.ALL,ZohoCRM.Files.READ"
HUBSPOT_SCOPE = "crm.import files crm.objects.deals.read crm.objects.deals.write"
TOKEN_FILE = "zoho_tokens.json"
HUBSPOT_TOKEN_FILE = "hubspot_tokens.json"
FOLDER_CONFIG_FILE = "hubspot_folder_config.json"
DB_FILE = "migration.db"  # Initialize DB_FILE here
ATTACHMENTS_FOLDER = os.getenv("ATTACHMENTS_FOLDER", "attachments")

# Global variable to store authorization code and folder ID
AUTH_CODE = None
HUBSPOT_FOLDER_ID = None
CURRENT_SERVICE = None  # To track which service is being authorized
ZOHO_ACCESS_TOKEN = None  # Global to store Zoho token

# HTTP server to capture OAuth code and handle folder selection
class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE, HUBSPOT_FOLDER_ID, CURRENT_SERVICE
        print(f"Received request: {self.path}")
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        if 'code' in query_params:
            AUTH_CODE = query_params['code'][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            if CURRENT_SERVICE == "zoho":
                self.wfile.write(b"<html><body><h1>Zoho authorization successful! Proceeding to HubSpot...</h1></body></html>")
                CURRENT_SERVICE = "hubspot"
                auth_url = f"{HUBSPOT_AUTH_URL}?client_id={HUBSPOT_CLIENT_ID}&scope={HUBSPOT_SCOPE}&redirect_uri={REDIRECT_URI}&response_type=code"
                webbrowser.open(auth_url)
            elif CURRENT_SERVICE == "hubspot" and not HUBSPOT_FOLDER_ID:
                self.wfile.write(b"<html><body><h1>Authorization successful! Please select a HubSpot folder or enter its ID.</h1>")
                self.wfile.write(b"<form action='/select_folder' method='post'>")
                self.wfile.write(b"<label for='folder_id'>Folder ID:</label><input type='text' id='folder_id' name='folder_id'><br>")
                self.wfile.write(b"<input type='submit' value='Submit'></form>")
                self.wfile.write(b"</body></html>")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Page not found</h1></body></html>")

    def do_POST(self):
        global AUTH_CODE, HUBSPOT_FOLDER_ID
        print(f"Received POST request: {self.path}")
        if self.path.startswith('/select_folder') and AUTH_CODE:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode()
            folder_id = parse_qs(post_data).get('folder_id', [''])[0]
            if folder_id:
                HUBSPOT_FOLDER_ID = folder_id
                save_folder_config(HUBSPOT_FOLDER_ID)
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Folder selected! You can close this window.</h1></body></html>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Error: No folder ID provided")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Invalid request</h1></body></html>")

def save_folder_config(folder_id):
    with open(FOLDER_CONFIG_FILE, 'w') as f:
        json.dump({"folder_id": folder_id}, f)

def load_folder_config():
    global HUBSPOT_FOLDER_ID
    if os.path.exists(FOLDER_CONFIG_FILE):
        with open(FOLDER_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            HUBSPOT_FOLDER_ID = config.get("folder_id")
    return HUBSPOT_FOLDER_ID

# Load or refresh Zoho tokens
def load_zoho_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            tokens = json.load(f)
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')
            expires_at = tokens.get('expires_at', 0)
            if expires_at > time.time() + 300:
                return access_token
            if refresh_token:
                return refresh_zoho_token(refresh_token)
    return None  # Token will be set by the server in migrate_attachments

# Refresh Zoho access token
def refresh_zoho_token(refresh_token):
    print("Refreshing Zoho access token...")
    payload = {
        "refresh_token": refresh_token,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    try:
        response = requests.post(ZOHO_TOKEN_URL, data=payload)
        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            tokens = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": time.time() + expires_in
            }
            with open(TOKEN_FILE, 'w') as f:
                json.dump(tokens, f)
            print("✅ Access token refreshed")
            return access_token
        else:
            print(f"❌ Failed to refresh token: {response.status_code} - {response.text}")
            return get_new_zoho_token()
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return get_new_zoho_token()

# Get new Zoho access token via OAuth
def get_new_zoho_token():
    global AUTH_CODE, CURRENT_SERVICE
    AUTH_CODE = None
    CURRENT_SERVICE = "zoho"
    auth_url = f"{ZOHO_AUTH_URL}?scope={ZOHO_SCOPE}&client_id={ZOHO_CLIENT_ID}&response_type=code&access_type=offline&redirect_uri={REDIRECT_URI}"
    print(f"Opening browser for Zoho authorization: {auth_url}")
    webbrowser.open(auth_url)
    return AUTH_CODE  # Will be set by the server

# Load or refresh HubSpot tokens
def load_hubspot_tokens():
    if os.path.exists(HUBSPOT_TOKEN_FILE):
        with open(HUBSPOT_TOKEN_FILE, 'r') as f:
            tokens = json.load(f)
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')
            expires_at = tokens.get('expires_at', 0)
            if expires_at > time.time() + 300:
                return access_token
            if refresh_token:
                return refresh_hubspot_token(refresh_token)
    return None  # Token will be set by the server in migrate_attachments

# Refresh HubSpot access token
def refresh_hubspot_token(refresh_token):
    print("Refreshing HubSpot access token...")
    payload = {
        "refresh_token": refresh_token,
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    try:
        response = requests.post(HUBSPOT_TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 21600)
            tokens = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": time.time() + expires_in
            }
            with open(HUBSPOT_TOKEN_FILE, 'w') as f:
                json.dump(tokens, f)
            print("✅ HubSpot access token refreshed")
            return access_token
        else:
            print(f"❌ Failed to refresh token: {response.status_code} - {response.text}")
            return get_new_hubspot_token()
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return get_new_hubspot_token()

# Get new HubSpot access token via OAuth
def get_new_hubspot_token():
    global AUTH_CODE, HUBSPOT_FOLDER_ID
    if not AUTH_CODE or not HUBSPOT_FOLDER_ID:
        raise Exception("HubSpot authorization or folder ID not completed")
    payload = {
        "grant_type": "authorization_code",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": AUTH_CODE
    }
    try:
        response = requests.post(HUBSPOT_TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 21600)
            tokens = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": time.time() + expires_in
            }
            with open(HUBSPOT_TOKEN_FILE, 'w') as f:
                json.dump(tokens, f)
            print("✅ New HubSpot tokens saved")
            return access_token
        else:
            raise Exception(f"Failed to get HubSpot tokens: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Request failed: {e}")

def get_zoho_headers():
    access_token = load_zoho_tokens()
    return {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }

# Initialize HubSpot headers with dynamic token
def get_hubspot_headers():
    access_token = load_hubspot_tokens()
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

# Initialize or connect to SQLite database with created_date
def init_db():
    conn = sqlite3.connect(DB_FILE)  # Now DB_FILE is initialized
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attachments
                 (zoho_deal_id TEXT, zoho_attachment_id TEXT, file_name TEXT, file_path TEXT,
                  hubspot_attachment_id TEXT, hubspot_deal_id TEXT, hubspot_note_id TEXT, status TEXT, created_date TEXT)''')
    conn.commit()
    return conn

# Fetch deals from Zoho CRM
def get_zoho_deals():
    print("--------------------------------Fetching deals from Zoho--------------------------------")
    url = f"{ZOHO_API_BASE}/Deals"
    params = {"fields": "id,Deal_Name,Stage,Amount"}
    try:
        response = requests.get(url, headers=get_zoho_headers(), params=params)
        if response.status_code == 200:
            return response.json().get("data", [])
        else:
            print(f"Failed to fetch deals: {response.status_code} - {response.text}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"Request failed while fetching deals: {e}")
        return []

# Fetch attachments for a Zoho deal
def get_zoho_attachments(deal_id):
    print(f"--------------------------------Fetching attachments for Zoho Deal ID: {deal_id}--------------------------------")
    url = f"{ZOHO_API_BASE}/Deals/{deal_id}/Attachments"
    params = {"fields": "id,File_Name,Size,Created_Time"}
    try:
        response = requests.get(url, headers=get_zoho_headers(), params=params)
        if response.status_code == 200:
            return response.json().get("data", [])
        elif response.status_code == 204:
            return []
        else:
            print(f"Failed to fetch attachments: {response.status_code} - {response.text}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return []

# Download attachment from Zoho CRM
def download_zoho_attachment(deal_id, attachment_id, file_name):
    print(f"--------------------------------Downloading attachment: {file_name}--------------------------------")
    url = f"{ZOHO_API_BASE}/Attachments/{attachment_id}"
    try:
        response = requests.get(url, headers=get_zoho_headers(), stream=True)
        if response.status_code == 200:
            content_disposition = response.headers.get("Content-Disposition", "")
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[1].strip('"; ')
            else:
                content_type = response.headers.get("Content-Type", "").lower().split(";")[0].strip()
                extension_map = {
                    "application/pdf": ".pdf", "application/msword": ".doc",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                    "video/mp4": ".mp4", "video/quicktime": ".mov", "audio/mpeg": ".mp3",
                    "image/png": ".png", "image/jpeg": ".jpg", "application/x-download": ".xlsx",
                    "text/csv": ".csv", "application/xml": ".xml"
                }
                extension = extension_map.get(content_type, ".bin")
                filename = f"attachment_{attachment_id}{extension}" if not file_name.endswith(extension) else file_name

            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(ATTACHMENTS_FOLDER, filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1

            file_path = os.path.join(ATTACHMENTS_FOLDER, filename)
            os.makedirs(ATTACHMENTS_FOLDER, exist_ok=True)
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"✅ Downloaded: {file_path}")
            return file_path
        elif response.status_code == 204:
            print("⚠️ No content. Skipping.")
            return None
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

# Upload file to HubSpot and get attachment ID
def upload_to_hubspot(file_path):
    print(f"--------------------------------Uploading to HubSpot: {os.path.basename(file_path)}--------------------------------")
    url = "https://api.hubapi.com/files/v3/files"  # HubSpot Files API endpoint
    headers = {
        "Authorization": f"Bearer {load_hubspot_tokens()}",
        "accept": "application/json"
    }
    
    # Determine the MIME type of the file
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"  # Default if MIME type is unknown
    
    # Prepare the file for upload using multipart/form-data
    with open(file_path, "rb") as file:
        files = {
            "file": (os.path.basename(file_path), file, content_type)
        }
        try:
            response = requests.post(url, headers=headers, files=files)
            if response.status_code == 201:  # 201 Created for successful upload
                data = response.json()
                hs_attachment_id = data.get("id")
                print(f"✅ Uploaded. HubSpot Attachment ID: {hs_attachment_id}")
                return hs_attachment_id
            else:
                print(f"❌ Failed: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed: {e}")
            return None

# Fetch HubSpot deal ID using zoho_deal_id custom property with pagination
def get_hubspot_deal_id(zoho_deal_id):
    print(f"--------------------------------Fetching HubSpot Deal ID for Zoho Deal ID: {zoho_deal_id}--------------------------------")
    url = HUBSPOT_DEALS_API
    params = {
        "properties": "zoho_deal_id",
        "limit": 100,
        "archived": False
    }
    after = 0
    while True:
        if after:
            params["after"] = after
        try:
            response = requests.get(url, headers=get_hubspot_headers(), params=params)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                for deal in results:
                    properties = deal.get("properties", {})
                    if properties.get("zoho_deal_id") == zoho_deal_id:
                        print(f"✅ Found HubSpot Deal ID: {deal['id']} for Zoho Deal ID: {zoho_deal_id}")
                        return deal["id"]
                after = data.get("paging", {}).get("next", {}).get("after")
                if not after:
                    break
            else:
                print(f"❌ Failed to fetch deals: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed: {e}")
            return None
    print(f"⚠️ No matching HubSpot deal found for Zoho Deal ID: {zoho_deal_id}")
    return None

# Create note with attachment and associate with HubSpot deal
def create_note_with_attachment(hs_attachment_id, hubspot_deal_id, zoho_deal_id):
    print(f"--------------------------------Creating note with attachment ID: {hs_attachment_id}--------------------------------")
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    note_body = f"Zoho Deal ID: {zoho_deal_id}"
    payload = {
        "properties": {
            "hs_timestamp": timestamp_ms,
            "hs_note_body": note_body,
            "hubspot_owner_id": "671151283",
            "hs_attachment_ids": hs_attachment_id
        },
        "associations": [
            {
                "to": {"id": hubspot_deal_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 214}]
            }
        ]
    }
    try:
        response = requests.post(HUBSPOT_NOTES_API, headers=get_hubspot_headers(), json=payload)
        if response.status_code == 201:
            note_data = response.json()
            note_id = note_data.get("id")
            print(f"✅ Created note (Note ID: {note_id}) for Deal ID: {hubspot_deal_id}")
            return note_id
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

# Process migration for all Zoho deals
def migrate_attachments():
    print("Starting authorization flows...")
    global AUTH_CODE, HUBSPOT_FOLDER_ID, CURRENT_SERVICE
    AUTH_CODE = None
    HUBSPOT_FOLDER_ID = None
    CURRENT_SERVICE = "zoho"

    with socketserver.TCPServer(("", 8000), OAuthHandler) as httpd:
        # Start Zoho authorization
        auth_url = f"{ZOHO_AUTH_URL}?scope={ZOHO_SCOPE}&client_id={ZOHO_CLIENT_ID}&response_type=code&access_type=offline&redirect_uri={REDIRECT_URI}"
        print(f"Opening browser for Zoho authorization: {auth_url}")
        webbrowser.open(auth_url)
        while not AUTH_CODE or CURRENT_SERVICE != "hubspot":
            httpd.handle_request()
            if AUTH_CODE and CURRENT_SERVICE == "zoho":
                print("Zoho authorization completed. Proceeding to HubSpot...")
                payload = {
                    "code": AUTH_CODE,
                    "client_id": ZOHO_CLIENT_ID,
                    "client_secret": ZOHO_CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code"
                }
                try:
                    response = requests.post(ZOHO_TOKEN_URL, data=payload)
                    if response.status_code == 200:
                        data = response.json()
                        access_token = data.get("access_token")
                        refresh_token = data.get("refresh_token")
                        expires_in = data.get("expires_in", 3600)
                        tokens = {
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "expires_at": time.time() + expires_in
                        }
                        with open(TOKEN_FILE, 'w') as f:
                            json.dump(tokens, f)
                        print("✅ New Zoho tokens saved")
                    else:
                        raise Exception(f"Failed to get Zoho tokens: {response.status_code} - {response.text}")
                except requests.exceptions.RequestException as e:
                    raise Exception(f"Request failed: {e}")

        # Start HubSpot authorization
        CURRENT_SERVICE = "hubspot"
        auth_url = f"{HUBSPOT_AUTH_URL}?client_id={HUBSPOT_CLIENT_ID}&scope={HUBSPOT_SCOPE}&redirect_uri={REDIRECT_URI}&response_type=code"
        print(f"Opening browser for HubSpot authorization: {auth_url}")
        webbrowser.open(auth_url)
        while not HUBSPOT_FOLDER_ID:
            httpd.handle_request()
            if AUTH_CODE and not HUBSPOT_FOLDER_ID:
                print("Waiting for folder ID submission...")

        # Save HubSpot token
        payload = {
            "grant_type": "authorization_code",
            "client_id": HUBSPOT_CLIENT_ID,
            "client_secret": HUBSPOT_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": AUTH_CODE
        }
        try:
            response = requests.post(HUBSPOT_TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token")
                refresh_token = data.get("refresh_token")
                expires_in = data.get("expires_in", 21600)
                tokens = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": time.time() + expires_in
                }
                with open(HUBSPOT_TOKEN_FILE, 'w') as f:
                    json.dump(tokens, f)
                print("✅ New HubSpot tokens saved")
            else:
                raise Exception(f"Failed to get HubSpot tokens: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {e}")

    if not HUBSPOT_FOLDER_ID:
        print("HubSpot folder ID not found. Please complete the OAuth flow and select a folder.")
        return

    conn = init_db()
    c = conn.cursor()
    deals = get_zoho_deals()
    for deal in deals:
        zoho_deal_id = deal.get("id")
        deal_name = deal.get("Deal_Name", "Unknown Deal")
        print(f"\nProcessing Deal: {deal_name} (Zoho ID: {zoho_deal_id})")
        attachments = get_zoho_attachments(zoho_deal_id)
        if attachments:
            for attachment in attachments:
                zoho_attachment_id = attachment.get("id")
                file_name = attachment.get("File_Name", f"attachment_{zoho_attachment_id}")
                c.execute("SELECT hubspot_attachment_id FROM attachments WHERE zoho_deal_id = ? AND zoho_attachment_id = ?", (zoho_deal_id, zoho_attachment_id))
                if c.fetchone():
                    print(f"✅ Already processed: {file_name}. Skipping.")
                    continue
                file_path = download_zoho_attachment(zoho_deal_id, zoho_attachment_id, file_name)
                if file_path:
                    created_date = datetime.now(timezone.utc).isoformat()
                    c.execute("INSERT INTO attachments (zoho_deal_id, zoho_attachment_id, file_name, file_path, status, created_date) VALUES (?, ?, ?, ?, ?, ?)",
                              (zoho_deal_id, zoho_attachment_id, file_name, file_path, "downloaded", created_date))
                    conn.commit()
                    print(f"✅ Stored in database: {file_name}")
                    hs_attachment_id = upload_to_hubspot(file_path)
                    if hs_attachment_id:
                        hubspot_deal_id = get_hubspot_deal_id(zoho_deal_id)
                        if hubspot_deal_id:
                            hubspot_note_id = create_note_with_attachment(hs_attachment_id, hubspot_deal_id, zoho_deal_id)
                            if hubspot_note_id:
                                c.execute("UPDATE attachments SET hubspot_attachment_id = ?, hubspot_deal_id = ?, hubspot_note_id = ?, status = ? WHERE zoho_deal_id = ? AND zoho_attachment_id = ?",
                                          (hs_attachment_id, hubspot_deal_id, hubspot_note_id, "uploaded", zoho_deal_id, zoho_attachment_id))
                                conn.commit()
                                print(f"✅ Updated database with status 'uploaded' for {file_name}")
                        os.remove(file_path)
    conn.close()

if __name__ == "__main__":
    migrate_attachments()