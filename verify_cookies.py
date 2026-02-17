import httpx
import time
import json

def verify():
    base_url = "http://localhost:5000"
    
    # 1. Register a test user (ignoring if already exists)
    user_data = {
        "name": "Cookie Tester",
        "email": "cookie@test.com",
        "password": "strongpassword123"
    }
    httpx.post(f"{base_url}/users", json=user_data)
    
    # 2. Login and check for Cookie
    print("Logging in...")
    login_data = {"email": "cookie@test.com", "password": "strongpassword123"}
    response = httpx.post(f"{base_url}/users/login", json=login_data)
    
    if response.status_code != 200:
        print(f"Login failed: {response.text}")
        return

    # Check body
    body = response.json()
    if "token" in body:
        print("✅ Token found in body.")
    else:
        print("❌ Token NOT found in body.")
        
    # Check cookies
    cookies = response.cookies
    if "access_token" in cookies:
        print(f"✅ access_token cookie found: {cookies['access_token'][:10]}...")
    else:
        print("❌ access_token cookie NOT found.")
        print(f"Set-Cookie headers: {response.headers.get('set-cookie')}")

    # 3. Access protected route WITH Cookie (no Bearer header)
    print("\nTesting /users/me using ONLY cookie...")
    headers = {} # No Authorization header
    response_me = httpx.get(f"{base_url}/users/me", cookies=cookies)
    
    if response_me.status_code == 200:
        print(f"✅ Successfully accessed /users/me using cookie: {response_me.json().get('user', {}).get('email')}")
    else:
        print(f"❌ Failed to access /users/me using cookie: {response_me.status_code} - {response_me.text}")

    # 4. Access protected route WITH Bearer (legacy support)
    print("\nTesting /users/me using legacy Bearer token...")
    token = body.get("token")
    headers = {"Authorization": f"Bearer {token}"}
    # Clear cookies for this request to be sure
    response_legacy = httpx.get(f"{base_url}/users/me", headers=headers)
    
    if response_legacy.status_code == 200:
        print(f"✅ Successfully accessed /users/me using legacy Bearer token.")
    else:
        print(f"❌ Failed to access /users/me using legacy Bearer token: {response_legacy.status_code}")

if __name__ == "__main__":
    verify()
