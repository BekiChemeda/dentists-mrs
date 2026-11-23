# Email

Clinic MRS can email staff. It is **off** until a system administrator sets it up in
**System › Email**. Nothing needs installing on the server apart from the timer below (once per installation).

## What is emailed

| Who | What | Content |
| --- | --- | --- |
| System administrators | Health warnings (disk, backups, errors), off-site backup overdue, audit-log tampering, unused accounts switched off, new two-step enrolments | Full text (no patient data in these) |
| Each person, about their own account | Password changed or reset, account locked, two-step sign-in turned on, off or reset, new recovery codes | Full text. Never a password. |
| Staff who choose it | Their in-app notifications. **Important only** (default): emergencies, critical results, approvals, system problems. **Everything**, or **None**. Chosen under *name menu › Security and alerts* | Patient-related notices are generic ("A critical laboratory result needs your attention") with a link; no names, MRNs or results |

Email providers may store messages outside Ethiopia, and health data is sensitive personal data under the
Personal Data Protection Proclamation No. 1321/2024, so **no patient information is ever put in an email**.
Patient emails (reminders, results) and "forgot password" by email are not included.

## Option 1: the clinic's own address from its web host (cPanel)

1. cPanel › **Email Accounts** › Create: e.g. `mrs@yourclinic.et` with a strong password.
2. Click **Connect Devices** next to it. Note the *Outgoing Server* name and *SMTP Port*.
3. In Clinic MRS › System › Email choose **Clinic email (cPanel)** and fill in:
   - Send from: `mrs@yourclinic.et`; Username: the same address; Password: that account's password.
   - Server: as shown in Connect Devices (often `mail.yourclinic.et`); Security: SSL/TLS on 465
     (or STARTTLS on 587 if the host says so).
4. **Send test email**, then **Save** and switch email **on**.

Deliverability: in cPanel › **Email Deliverability**, make sure SPF and DKIM show as valid for the domain
(cPanel can install them with one click when the domain's DNS is on the same host).

## Option 2: Brevo

1. Create a free account at brevo.com (300 emails a day free).
2. **Senders, Domains & Dedicated IPs**: add the clinic's address (or better, the domain) and verify it;
   for a domain, add the DNS records Brevo shows (DKIM, and the Brevo code), so mail is not marked as spam.
3. **SMTP & API › SMTP**: copy the **SMTP login** and **generate an SMTP key**.
4. In Clinic MRS › System › Email choose **Brevo**. The server (`smtp-relay.brevo.com`, STARTTLS, 587) is
   filled in. Enter the SMTP login as username, the SMTP key as password, and the verified address as
   *Send from*.
5. **Send test email**, then **Save** and switch email **on**.

## How sending works

- Emails go into an **outbox** in the database and are sent every minute by
  `deploy/systemd/mrs-email.timer`. Install it once:
  ```
  sudo cp deploy/systemd/mrs-email.{service,timer} /etc/systemd/system/
  sudo systemctl daemon-reload && sudo systemctl enable --now mrs-email.timer
  ```
- If the internet or the email server is down, messages wait and are retried after 1, 5, 15, 30 minutes,
  then hourly, up to 8 tries; then they are marked **Failed** and can be retried from System › Email.
- If the action that caused an email is cancelled (an error rolls it back), the email is not sent.
- The password or SMTP key is stored **encrypted** (key derived from `DJANGO_SECRET_KEY`); it is never shown
  again or written to the audit log. If `DJANGO_SECRET_KEY` changes, enter the password again.
- Every settings change and test is in the audit log.

## Problems

| Message | Fix |
| --- | --- |
| The server refused the username or password | Retype the password (cPanel) or create a new SMTP key (Brevo). |
| The server refused the From address | Brevo: verify the sender/domain. cPanel: send from the same address as the username. |
| The secure connection failed | Switch between SSL/TLS on 465 and STARTTLS on 587. |
| The server name could not be found / did not answer | Check the server name and that the clinic server has internet. Some networks block port 465 or 587: try the other. |
| Emails arrive in spam | Add SPF and DKIM for the domain (cPanel Email Deliverability, or Brevo domain authentication). |
