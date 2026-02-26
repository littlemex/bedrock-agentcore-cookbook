"""
Pre Token Generation Lambda Trigger for Cognito

This Lambda function adds custom attributes to Access Token claims.
- custom:tenant_id -> tenant_id claim
- custom:role -> role claim (default: "guest")
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Pre Token Generation Lambda Trigger

    Event structure:
    {
        "version": "1",
        "triggerSource": "TokenGeneration_Authentication",
        "userPoolId": "...",
        "userName": "...",
        "request": {
            "userAttributes": {
                "sub": "...",
                "email": "...",
                "custom:tenant_id": "...",
                "custom:role": "..."
            },
            "groupConfiguration": {...}
        },
        "response": {
            "claimsOverrideDetails": {
                "claimsToAddOrOverride": {},
                "claimsToSuppress": [],
                "groupOverrideDetails": null
            }
        }
    }
    """

    try:
        logger.info(f"Pre Token Generation triggered for user: {event.get('userName')}")

        # Get user attributes
        user_attributes = event.get('request', {}).get('userAttributes', {})

        # Extract custom attributes
        tenant_id = user_attributes.get('custom:tenant_id', '')
        role = user_attributes.get('custom:role', 'guest')

        # Add custom claims to Access Token
        if 'response' not in event:
            event['response'] = {}

        if 'claimsOverrideDetails' not in event['response']:
            event['response']['claimsOverrideDetails'] = {}

        # Add claims to both Access Token and ID Token
        event['response']['claimsOverrideDetails'] = {
            'claimsToAddOrOverride': {
                'tenant_id': tenant_id,
                'role': role
            }
        }

        logger.info(f"Added claims - tenant_id: {tenant_id}, role: {role}")

        return event

    except Exception as e:
        logger.error(f"Pre Token Generation failed: {e}")
        # Return event unchanged to avoid blocking authentication
        return event
