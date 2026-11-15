# Configure sign-in

Add these entries to the repository root `.env`, alongside the Groq key if you already use one. Compose passes the credentials to the API.

```dotenv
INQUEST_WEB_ORIGIN=http://localhost:5173
INQUEST_GITHUB_CLIENT_ID=
INQUEST_GITHUB_CLIENT_SECRET=
INQUEST_GOOGLE_CLIENT_ID=
INQUEST_GOOGLE_CLIENT_SECRET=
```

1. In [GitHub Developer Settings](https://github.com/settings/developers), create an **OAuth App**. Set the homepage URL to `http://localhost:5173` and the authorization callback URL to `http://localhost:5173/api/v1/auth/github/callback`. Generate a client secret and fill in the GitHub entries.
2. In [Google Auth Platform](https://console.cloud.google.com/auth/clients), configure branding and audience, then create a **Web application** client. Add `http://localhost:5173/api/v1/auth/google/callback` under **Authorized redirect URIs**. For an app in Testing, include your Google account in the test-user list. Fill in the Google entries.
3. Open the app at `http://localhost:5173`. After changing credentials, recreate the API with `docker compose up -d --force-recreate api`.

A provider needs both its client ID and secret to appear enabled. The first successful sign-in creates a personal workspace. Each provider account is a distinct identity.

The root `.env` is ignored by Git. Use fresh OAuth apps and an HTTPS `INQUEST_WEB_ORIGIN` for a deployment, and register the matching callback URLs on that origin. For rate limits across API processes, set the same random `INQUEST_IP_HASH_SECRET` on every process. Only trust forwarded IP headers from a configured reverse proxy.

[GitHub authorization documentation](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) · [Google OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect)
