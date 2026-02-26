#!/usr/bin/env python3
"""Debug script to decode Cognito Access Token and inspect claims"""

import boto3
import os
import sys
import json
import hmac
import hashlib
import base64
import jwt

# Load environment from .env
env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

region = os.getenv('AWS_REGION', 'us-east-1')
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
user_pool_id = os.getenv('USER_POOL_ID')

cognito_client = boto3.client('cognito-idp', region_name=region)

def calculate_secret_hash(username):
    message = username + client_id
    dig = hmac.new(
        client_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(dig).decode()

# Get token for admin@tenant-a
username = 'admin@tenant-a.example.com'
password = 'TempPass123!'

print(f"[DEBUG] Getting token for: {username}")

auth_params = {
    'USERNAME': username,
    'PASSWORD': password
}

secret_hash = calculate_secret_hash(username)
if secret_hash:
    auth_params['SECRET_HASH'] = secret_hash

response = cognito_client.initiate_auth(
    ClientId=client_id,
    AuthFlow='USER_PASSWORD_AUTH',
    AuthParameters=auth_params
)

access_token = response['AuthenticationResult']['AccessToken']
id_token = response['AuthenticationResult']['IdToken']

print("\n" + "="*80)
print("ACCESS TOKEN CLAIMS (unverified decode):")
print("="*80)
access_claims = jwt.decode(access_token, options={"verify_signature": False})
print(json.dumps(access_claims, indent=2))

print("\n" + "="*80)
print("ID TOKEN CLAIMS (unverified decode):")
print("="*80)
id_claims = jwt.decode(id_token, options={"verify_signature": False})
print(json.dumps(id_claims, indent=2))

print("\n" + "="*80)
print("KEY CHECKS:")
print("="*80)
print(f"Access Token has 'client_id': {'client_id' in access_claims}")
print(f"Access Token has 'tenant_id': {'tenant_id' in access_claims}")
print(f"Access Token has 'role': {'role' in access_claims}")
print(f"Access Token 'token_use': {access_claims.get('token_use')}")
