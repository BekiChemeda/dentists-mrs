# ADR 0002 — Server-side cookie sessions instead of JWT

Date: 2026-11-20 · Status: accepted

## Decision

Authenticate the SPA with Django's server-side sessions (HttpOnly cookie, SameSite=Lax, Secure under HTTPS) and CSRF tokens. No JWTs or tokens in browser storage.

## Reasons

- Sessions can be revoked instantly (deactivation, password change, "sign out everywhere"); stateless JWTs cannot without extra infrastructure.
- HttpOnly cookies cannot be read by injected JavaScript; tokens in localStorage can.
- The SPA and API share one origin behind Nginx, so cookies work without CORS.

## Consequences

- Every unsafe request carries `X-CSRFToken`; the login endpoint enforces CSRF explicitly because DRF skips it for anonymous users.
- A `UserSession` table maps session keys to users to support listing and revocation, and to enforce a 12-hour absolute lifetime on top of the 30-minute idle timeout.
- A future mobile client would need a separate token scheme, designed then.
