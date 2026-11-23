# ADR 0004 — Administrator-issued temporary passwords

Date: 2026-11-20 · Status: accepted

## Context

The system must work without internet, and many clinics have no mail relay. Self-service reset needs a trusted second channel.

## Decision

Administrators (`users.manage`) issue a random one-time temporary password, shown once on screen and never stored in plain text or logged. The account is flagged `must_change_password`; until the user sets their own password, every API endpoint except "me", "change password" and "logout" returns `password_change_required`. Issuing a reset ends all of that user's sessions and clears any lockout.

## Consequences

- Staff must see an administrator in person to recover access — acceptable for a single-site clinic.
- Email or SMS self-service reset can be added later as an additional channel when the clinic has one.
