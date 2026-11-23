# Payments by phone (Chapa and telebirr)

Cash is always available and is the default. Payments by phone are an optional, paid part of the licence:
the supplier issues the licence with `--online-payments` (see `phone-app.md`). Without it, nothing about
payments by phone appears and keys cannot be saved.

The money goes straight to the clinic's own Chapa or telebirr merchant account. Clinic MRS never holds money;
it asks the provider to send a prompt to the patient's phone and records the payment when the provider
confirms it.

## How a payment works

1. The cashier (website or phone app) opens an issued invoice, chooses **Pay by phone**, the method
   (telebirr, M-Pesa, CBE Birr, E-birr) and the patient's number.
2. The patient's phone shows a prompt. The patient enters only their PIN.
3. The screen shows "Waiting for the patient" and changes to **Paid** with a receipt number once the provider
   confirms. Nothing is recorded on the request alone.
4. No answer after 20 minutes: the request stops. A confirmation that arrives within the next hour is still
   recorded. If the bill was meanwhile paid in cash, the payment is marked **Paid twice: refund needed** and
   billing approvers are notified.

While a request waits, cash cannot be recorded on that invoice and no second request can be sent, so a
patient is never charged twice by mistake. **Stop** ends the wait.

## Providers

| | Chapa | telebirr (direct merchant) |
|---|---|---|
| Methods | telebirr, M-Pesa, CBE Birr, E-birr | telebirr |
| Clinic needs | a verified Chapa business account | a telebirr merchant account from Ethio Telecom (API access) |
| Confirmation | the server asks Chapa (works without a public address); Chapa's webhook speeds it up | telebirr calls the clinic's **public** address; no way to ask |
| Refunds | in the Chapa dashboard, then recorded in billing | in the telebirr merchant portal, then recorded in billing |

When both are set up, telebirr payments go directly through telebirr and the other methods through Chapa.

## Setting up (system administrator)

Administration › System › Payments by phone. Keys are stored encrypted and are never shown again; leave a
key field empty to keep the stored one.

**Chapa**
1. In the Chapa dashboard, copy the **secret key** (use the test key first). Choose the methods.
2. Optional, faster confirmations when the server is reachable from the internet: in Chapa's webhook settings
   set the URL to `https://<public address>/api/v1/payments/chapa/webhook/` and a random **secret hash**;
   enter the same secret hash here.
3. **Test connection**, then a small real payment.

**telebirr (direct)**
1. From Ethio Telecom: endpoint URL, third-party ID, password, initiator identifier and security credential,
   short code.
2. The clinic's public address (the remote address). telebirr sends results to the **result address** shown
   on the settings page; give it to Ethio Telecom if they ask for it. It contains a secret token.
3. On the server, add the endpoint's host name to `EGRESS_ALLOWED_HOSTS` in `.env` and restart
   (`docker compose up -d`).
4. Send a small real payment to check. telebirr has no test call.

## Network and security

- The API container has no internet. Requests to providers go through the `egress` container, which only
  connects to the hosts in `EGRESS_ALLOWED_HOSTS` (default `api.chapa.co`) on port 443. TLS is end to end:
  the relay sees no payment data or keys.
- Chapa's webhook must carry a valid HMAC signature, and even then the result is taken only from Chapa's
  verify call. A payment counts only if Chapa reports exactly the amount, currency and reference we sent.
- telebirr's result has no signature in this interface. It is accepted only at the secret result address and
  only for a request still waiting; the amount recorded is always the one stored when the request was made.
  Change the token by contacting support if the address leaks.
- `mrs-payments.timer` checks waiting requests every minute.

The telebirr direct interface was built from the published Huawei "Buy Goods for Customer" request format.
Confirm the details with Ethio Telecom's integration documents and test with a small amount before going live.
