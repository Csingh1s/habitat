# Microsoft Entra External ID setup

The mobile app and FastAPI API use Microsoft Entra External ID for real user authentication.
The API validates an Entra access token; it does not store or validate user passwords.

## Account-owner tasks

1. In Microsoft Entra admin center, create or select an **External ID customer tenant**.
2. Register an API application for Habitat:
   - Expose one delegated API scope, for example `access_as_user`.
   - Record the Application ID URI; FastAPI uses it as `OIDC_AUDIENCE`.
3. Register a native/mobile client application:
   - Add Android/iOS redirect URIs through the Expo/AuthSession implementation.
   - Grant it delegated permission to the Habitat API scope.
4. Configure the customer sign-up/sign-in user flow:
   - collect email and display name;
   - enable the desired providers, initially email/password;
   - require verification according to your company policy.
5. From the tenant OpenID Connect discovery document, record:
   - issuer URL;
   - JWKS URL;
   - API Application ID URI.

Do not share application secrets, administrator credentials, refresh tokens, or user passwords.
The mobile client uses PKCE and receives short-lived access tokens. FastAPI validates signatures
against the Entra JWKS, issuer, expiration, and audience.

## FastAPI staging configuration

Set these non-secret values in Azure Container Apps:

```text
OIDC_ISSUER_URL=<issuer from Entra discovery document>
OIDC_AUDIENCE=<Habitat API Application ID URI>
OIDC_JWKS_URL=<jwks_uri from Entra discovery document>
```

The Entra access token creates no automatic database row. The first authenticated user calls
`POST /v1/onboarding`; FastAPI atomically provisions the tenant and owner profile using the
token subject. Later users must be invited/provisioned by a tenant administrator before they
can access inspection data.
