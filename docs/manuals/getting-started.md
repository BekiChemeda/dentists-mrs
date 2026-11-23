# Getting started (everyone)

## Opening the system

Clinic MRS runs on the clinic's own server. Open a web browser (Chrome, Edge or Firefox) on any
clinic computer and type the address the administrator gave you, for example
`https://192.168.1.10` or `https://mrs.clinic.local`. Add it to the browser's bookmarks.

If the browser warns that the connection is not private, the clinic's certificate is not installed
on that computer. Do not click through the warning; ask the system administrator to install it
(see [system-administrator.md](system-administrator.md#https-certificate)).

## Signing in

1. Type your **Username** and **Password** and click **Sign in**.
2. The first time, you must choose a new password. Use at least 10 characters; a short sentence
   you can remember works well. Do not reuse a password from another website.
3. If your role needs **two-step sign-in**, you are asked to set it up (below) before you can continue.

After 5 wrong passwords in a row the account is locked for 15 minutes (the administrator may have
set different numbers). If you forgot your password, ask the system administrator or clinic
administrator for a temporary one; they will give it to you in person.

The system signs you out after 30 minutes without activity and at the latest after 12 hours. Always
use **Sign out** (menu under your name, top right) before leaving a shared computer.

## Two-step sign-in

Two-step sign-in asks for a 6-digit code from an app on your phone after the password, so a stolen
password alone is not enough. It is required for administrators and the clinic director, and
optional for everyone else unless the clinic turns it on for all.

1. Install an authenticator app on your phone: Google Authenticator, Microsoft Authenticator or Aegis.
2. Open the menu under your name › **Security and alerts**, and under **Two-step sign-in** click **Begin set-up**.
3. In the app, add an account and scan the QR code on the screen.
4. Type the 6-digit code the app shows and click **Turn on**.
5. The system shows **Your recovery codes**. Print them or copy them and keep them somewhere safe
   away from your phone, then click **I have saved them**. Each code lets you sign in once if you
   lose your phone.

At each sign-in, after your password, type the current code from the app. If the code is refused,
check that the phone's clock is set automatically; the codes depend on the correct time.

Lost your phone? Sign in with one of your recovery codes, then ask the system administrator to
reset your two-step sign-in so you can set it up on the new phone. If you have neither the phone nor
a recovery code, the administrator can still reset it after checking in person who you are.

## The screen

- **Menu** on the left: only the pages your role may use.
- **Search** at the top: press `/` anywhere and type a name, phone number or MRN to open a patient.
- **Bell**: notifications, such as critical results, approvals waiting, or a patient sent to you.
- **Your name** (top right): **Change password**, **Security and alerts** (two-step sign-in and email
  alerts), **Light / Dark / Device** appearance, and **Sign out**.
- **Dashboard**: your work for today, and any announcements from clinic management.

Dates are shown in the Gregorian calendar with the Ethiopian date beside them (the clinic can switch
the Ethiopian date off). Times are Ethiopian local time.

## Email alerts

If the clinic has set up email, you can choose under your name › **Security and alerts** which
notifications are also emailed to you: **Important only** (default), **Everything** or **None**.
Emails never contain patient details, only a link to sign in. Security notices about your own
account (for example a password reset) are always emailed.

## When someone else saved first

If two people edit the same record at the same time (for example two receptionists correcting the
same patient's phone number), the second save is refused instead of silently overwriting the
first person's work. You see **Someone else saved this record first**, with who saved it and when.

1. Click **Load the latest version**. The form closes and the record shows the current details.
2. Check what the other person changed, then open the form again and make your change if it is
   still needed.

Nothing you typed is saved until you do this, so nothing is lost without you knowing.

## Error messages

Messages say what went wrong and what to do. Some end with **Reference** and a code. If you need
help, give that reference to the administrator: it points to the exact request in the server logs.

If the system cannot be reached at all, continue on the paper forms and enter the records when it
is back (see [troubleshooting.md](troubleshooting.md)).
