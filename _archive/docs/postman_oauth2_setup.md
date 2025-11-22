# Postman Setup Guide: Okta OAuth2 with Private Key JWT

## What is This Guide For?

This guide helps you test Okta API calls in Postman using a **more secure authentication method** called `private_key_jwt`. 

**Why not just use Client ID + Client Secret?**

You can! But using a PEM certificate (private/public key pair) is more secure because:
- Your private key **never leaves your computer** or gets sent over the network
- You generate short-lived "proof tokens" (JWT Assertions) instead of using a permanent secret
- Even if someone intercepts your JWT, it expires in 5 minutes

**How does it work?**

Think of it like a secure handshake:

1. **Traditional Method (Client Secret):**
   - You: "Hi Okta, I'm Application X, here's my permanent secret password"
   - Okta: "Password checks out! Here's your access token"

2. **PEM Certificate Method (What we're doing):**
   - You: "Hi Okta, I'm Application X. I just signed this note with my private key to prove it's really me"
   - Okta: "Let me check that signature with the public key you gave me earlier... Yes, it's authentic! Here's your access token"

The **JWT Assertion** is that "signed note" - it acts like a temporary password that expires in 5 minutes.

---

## Prerequisites

Before you start, make sure you have:

- ✅ An Okta OAuth2 application set up in your Okta Admin Console
- ✅ Your **Client ID** (find it in the application settings)
- ✅ Your **Private Key** file in PEM format (e.g., `private_key.pem`)
- ✅ Your **Public Key** already uploaded to the Okta application
- ✅ Your **Okta domain** (e.g., `your-org.okta.com`)

---

## Step 1: Generate JWT Assertion (Your "Signed Note")

**What's happening here?** 

Postman can't create the special "signed note" (JWT Assertion) on its own. You need to generate it first using your private key. This JWT proves to Okta that you really are who you say you are.

**Important:** The JWT expires in **5 minutes**, so you'll need to regenerate it whenever you want a fresh access token.

### Option A: Use a Python Script (Recommended - Keeps Your Key Safe)

This method keeps your private key on your computer where it belongs.

1.  **Create a file called `generate_jwt.py` and paste this code:**

    ```python
    import time, jwt

    # --- UPDATE THESE VALUES ---
    CLIENT_ID = "your_client_id"              # From your Okta app settings
    OKTA_DOMAIN = "your-org.okta.com"         # Your Okta domain
    PRIVATE_KEY_PATH = "path/to/private_key.pem"  # Path to your PEM file
    # ---------------------------

    # Read your private key
    with open(PRIVATE_KEY_PATH, 'r') as f:
        private_key = f.read()

    # Build the token endpoint URL
    token_endpoint = f"https://{OKTA_DOMAIN}/oauth2/v1/token"
    current_time = int(time.time())

    # Create the claims (what goes in the "signed note")
    claims = {
        'aud': token_endpoint,              # Who you're talking to
        'iss': CLIENT_ID,                   # Who you are (issuer)
        'sub': CLIENT_ID,                   # Who you are (subject)
        'exp': current_time + 300,          # When this expires (5 minutes)
        'iat': current_time,                # When this was created
        'jti': f"jti-{current_time}"        # Unique ID for this JWT
    }

    # Sign the JWT with your private key
    jwt_assertion = jwt.encode(claims, private_key, algorithm='RS256')
    
    print("=" * 70)
    print("✅ JWT Assertion generated successfully!")
    print("=" * 70)
    print("\n📋 Copy this token (valid for 5 minutes):\n")
    print(jwt_assertion)
    print("\n" + "=" * 70)
    ```

2.  **Run the script:**
    ```bash
    # First time only: install the required libraries
    pip install pyjwt cryptography
    
    # Generate your JWT
    python generate_jwt.py
    ```

3.  **Copy the output token** - you'll paste this into Postman in Step 3.

### Option B: Use an Online Tool (Quick Test Only)

This is faster for a one-time test, but **not recommended for production**.

> **⚠️ Security Warning:** You'll be pasting your private key into a website. Only use this with a test/development key, NEVER with production credentials.

1.  **Go to [https://jwt.io](https://jwt.io)**
2.  **Algorithm:** Select `RS256` from the dropdown
3.  **Payload (left side):** Replace with this (update the values in quotes):
    ```json
    {
      "aud": "https://your-org.okta.com/oauth2/v1/token",
      "iss": "your_client_id",
      "sub": "your_client_id",
      "exp": 1729612800,
      "iat": 1729609200,
      "jti": "manual-jwt-test-123"
    }
    ```
    
4.  **Update timestamps:**
    - Go to [https://www.unixtimestamp.com](https://www.unixtimestamp.com) to get the current Unix timestamp
    - Set `iat` (issued at) to the current timestamp
    - Set `exp` (expires) to current timestamp + `300` (5 minutes from now)

5.  **Verify Signature (bottom right):** Paste your entire private key (including `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----`) into the "Private Key" box

6.  **Copy the Encoded JWT** from the left panel (the long string at the top)

---

## Step 2: Create Postman Collection

1. Open Postman
2. New → Collection → Name: `Okta OAuth2`
### Add Your Configuration Variables

Click on your new collection, then go to the **Variables** tab. Add these variables:

| Variable Name | Initial Value | What It's For |
|---------------|---------------|---------------|
| `okta_domain` | `your-org.okta.com` | Your Okta organization domain |
| `client_id` | `0oa1abc2def3ghi4jk5` | Your OAuth2 application's Client ID |
| `scopes` | `okta.users.read okta.apps.read` | What permissions you're requesting |
| `access_token` | *(leave empty)* | Will be auto-filled when you get a token |

**💡 Tip:** Replace the example values with your actual Okta domain and Client ID. The `access_token` will be populated automatically in the next step.

---

## Step 3: Get Your Access Token

**What's happening here?** 

You're sending your JWT Assertion to Okta and getting back an **access token** that you'll use for actual API calls. This access token is valid for **1 hour**.

### Create the Token Request

1. In your collection, click **Add request**
2. Name it: `1. Get Access Token`
3. Set the method to **POST**
4. Set the URL to: `https://{{okta_domain}}/oauth2/v1/token`

### Configure the Request Headers

Click the **Headers** tab and add:

```
Content-Type: application/x-www-form-urlencoded
Accept: application/json
```

### Configure the Request Body

1. Click the **Body** tab
2. Select **x-www-form-urlencoded**
3. Add these key-value pairs:

| Key | Value | What It Does |
|-----|-------|--------------|
| `grant_type` | `client_credentials` | Tells Okta you're using OAuth2 client credentials flow |
| `scope` | `{{scopes}}` | Uses the scopes from your collection variables |
| `client_assertion_type` | `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` | Tells Okta you're using JWT for authentication |
| `client_assertion` | *(paste your JWT from Step 1)* | Your "signed note" proving your identity |

**💡 Important:** Paste the JWT you generated in Step 1 into the `client_assertion` field.

### Auto-Save the Access Token

Click the **Tests** tab (next to Body) and paste this script:

```javascript
// This script automatically saves the access token when you get a successful response

var jsonData = pm.response.json();

if (jsonData.access_token) {
    // Save the token to your collection variables
    pm.collectionVariables.set("access_token", jsonData.access_token);
    
    console.log("✅ Access token saved successfully!");
    console.log("🕐 Token valid for: " + (jsonData.expires_in || 3600) + " seconds (usually 1 hour)");
} else {
    console.error("❌ No access token in response. Check the response below for errors.");
}
```

### Run the Request

1. Click the blue **Send** button
2. You should see a response like this:

```json
{
    "token_type": "Bearer",
    "expires_in": 3600,
    "access_token": "eyJraWQiOiJxxx...",
    "scope": "okta.users.read okta.apps.read"
}
```

3. Check the **Console** at the bottom - you should see "✅ Access token saved successfully!"

**🎉 Success!** Your access token is now saved in the collection variables and ready to use.

---

## Step 4: Make Your First API Call

**What's happening here?** 

Now that you have an access token, you can use it to make actual API calls to Okta. The token proves you're authorized.

### Create a Test Request (List Users)

1. In your collection, click **Add request**
2. Name it: `2. List Users (Test)`
3. Set the method to **GET**
4. Set the URL to: `https://{{okta_domain}}/api/v1/users?limit=10`

### Add the Authorization Header

Click the **Headers** tab and add:

```
Authorization: Bearer {{access_token}}
Accept: application/json
```

**💡 What's happening:** The `{{access_token}}` variable pulls in the token you saved in Step 3. The `Bearer` prefix tells Okta this is an OAuth2 token.

### Run the Request

1. Click **Send**
2. You should see a list of up to 10 users from your Okta organization

**🎉 Congratulations!** You've successfully authenticated and made an API call using the private key JWT method.

---

## Troubleshooting Common Issues

### Error: "invalid_client"
**What it means:** Okta couldn't verify your JWT Assertion.

**How to fix:**
- ✅ Regenerate your JWT (it expires in 5 minutes)
- ✅ Double-check that the `client_id` in your JWT matches your Okta application
- ✅ Verify the `aud` (audience) claim points to the correct token endpoint

### Error: "invalid_grant"
**What it means:** The JWT signature is invalid or the public/private key pair doesn't match.

**How to fix:**
- ✅ Verify your **public key** is uploaded to your Okta OAuth2 application
- ✅ Make sure your private key is in PEM format
- ✅ Confirm the public key in Okta matches the private key you're using

### Error: 401 Unauthorized on API calls
**What it means:** Your access token is missing, expired, or doesn't have the right permissions.

**How to fix:**
- ✅ Run the "Get Access Token" request first to get a fresh token
- ✅ Check that your scopes (`okta.users.read`, etc.) are granted to your OAuth2 application in Okta
- ✅ Access tokens expire after 1 hour - regenerate if needed

---

## Quick Reference

### Token Lifetimes
- **JWT Assertion:** 5 minutes (regenerate for each token request)
- **Access Token:** 1 hour (use for multiple API calls)

### When to Regenerate Tokens
1. **JWT Assertion:** Every time you need a new access token (or when it expires after 5 minutes)
2. **Access Token:** When you get a 401 error on API calls (typically after 1 hour)

### The Flow at a Glance
```
1. Generate JWT Assertion (Python script or jwt.io)
   ↓
2. Send JWT → Okta Token Endpoint
   ↓
3. Receive Access Token (saved automatically in Postman)
   ↓
4. Use Access Token for API calls (valid for 1 hour)
   ↓
5. When token expires → Go back to Step 1
```

---

**Note:** Remember to regenerate your JWT Assertion before each token request since it expires in 5 minutes!
