# Phone app: licence and activating phones

The Android app only works for a clinic that has paid for it, and only on phones the clinic's
administrator has activated. A copied app, a copied phone backup or a code borrowed from another clinic
does not work.

## How it is protected

| Check | Where | What it stops |
|---|---|---|
| Licence signed by the supplier, naming this server's installation ID, whether the app is included, the number of phones and the last day | server and app | clinics without the app; editing the licence; copying another clinic's licence |
| Activation code: one use, 15 minutes, only a hash stored, created by an administrator | server | strangers activating phones |
| Hardware key: made in the phone's secure area during activation, never leaves the phone; Google's attestation proves it | server | copying the app or its data to another phone; emulators; phones with modified system software |
| App package and (optional) supplier signing certificate inside the attestation | server | modified or re-signed copies of the app |
| Every app sign-in signs a one-time challenge with the hardware key, before the password is checked | server | password guessing from anything but an activated phone |
| App tokens are tied to the phone; switching the phone off or the licence ending stops them at once | server | lost phones; unpaid renewals |
| Server addresses come only from the signed licence; the HTTPS certificate fingerprint comes in the QR code | app | pointing the app at another server; fake servers |

The website is not affected by the licence: if the app licence ends, phones stop but the clinic keeps working
on computers.

What it cannot stop: two clinics running as one on a shared server. The phone limit, the activity list and
the contract cover that. The server runs on the clinic's own computer, so a skilled person could change its
code; the app also checks the supplier's signature, which raises the effort above the price of a licence.

## Supplier: once

1. On your own computer (not a clinic server): `pip install cryptography`, then
   `python vendor-tools/licence_tool.py keygen --out ~/mrs-supplier.key`.
   Choose a strong password. Back the key file up on an encrypted USB stick kept offline.
   Anyone with this file and password can issue licences.
2. The command prints the **public** key. Put it:
   - in the GitHub secret `VENDOR_PUBLIC_KEY` of the app repository, so release builds trust it;
   - in each clinic server's `.env` as `MRS_VENDOR_PUBLIC_KEYS=`.
3. Optional, stronger: put the SHA-256 of the app's release signing certificate (printed in the app build
   log) in each server's `.env` as `MOBILE_APP_SIGNATURE_SHA256=`.

## Supplier: per clinic

1. After installing the server, the installer prints the **installation ID**
   (or run `docker compose exec api python manage.py show_installation_id`).
2. Issue the licence:
   ```
   python vendor-tools/licence_tool.py sign --key ~/mrs-supplier.key \
     --clinic-id adama-family --clinic-name "Adama Family Clinic" \
     --installation-id <ID> --clinic-address https://192.168.1.10 \
     --remote-address https://mrs.adamafamily.et --phones 10 --until 2027-11-30 \
     --out adama-family.licence
   ```
3. Install it: **Administration › Phones › Licence** (system administrator), or
   `docker compose exec -T api python manage.py install_licence /dev/stdin < adama-family.licence`.
4. To renew, add phones or change addresses, issue a new licence with the same installation ID and install it.
   A reinstalled server gets a new installation ID only if its database is not restored from backup.

## Clinic administrator: activating a phone

1. **Administration › Phones › Activate a phone.** Optionally choose the staff member the phone is for
   (leave empty for a shared ward phone).
2. On the phone, open Clinic MRS and scan the QR code within 15 minutes. The app checks the licence, makes its
   hardware key and activates.
3. Staff sign in with their own username and password.
4. A lost or replaced phone: **Switch off** it in the list. Its sign-ins end immediately and it frees a place.
5. Reinstalling the app or changing phones needs a new activation, like mobile banking.
