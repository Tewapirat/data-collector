import requests
import msal

CLIENT_ID = "YOUR_CLIENT_ID"  # ใส่ Client ID ของแอปที่ลงทะเบียนใน Azure AD
TENANT_ID = "YOUR_TENANT_ID"  # ใส่ Tenant ID จริงๆ จาก Azure ห้ามใช้ "consumers"

FOLDER_NAME = "demo-upload-file"
FILE_NAME = "test_upload.csv"
test_content = "name,age,city\nJohn,25,Bangkok\nJane,30,London"

# Login ด้วย Work Account
app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}"  # ต้องเป็น Tenant ID จริง
)

token_result = app.acquire_token_interactive(
    scopes=["https://graph.microsoft.com/Files.ReadWrite",
            "https://graph.microsoft.com/User.Read"]
)

if "access_token" not in token_result:
    print("❌ Login ไม่สำเร็จ:", token_result.get("error_description"))
    exit()

print("✅ Login สำเร็จ!")
access_token = token_result["access_token"]

upload_headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "text/csv"
}

url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{FOLDER_NAME}/{FILE_NAME}:/content"

response = requests.put(url, headers=upload_headers, data=test_content.encode("utf-8"))

if response.status_code in [200, 201]:
    file_info = response.json()
    print("✅ Upload สำเร็จ!")
    print(f"📁 ไฟล์อยู่ที่: {FOLDER_NAME}/{file_info['name']}")
    print(f"🔗 ลิงก์: {file_info['webUrl']}")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.json())