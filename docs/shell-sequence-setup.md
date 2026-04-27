# Shell Sequence Setup (One-Time, Manual)

The sending-mcp depends on a pre-built "shell sequence" in Apollo. Sequences **cannot be created via API** — you must set this up in the Apollo UI.

## Steps

### 1. Create Custom Contact Fields

In Apollo, go to **Settings → Custom Fields → Contact Fields** and create:

| Field Name | Type |
|---|---|
| `ai_email_subject` | Text |
| `ai_email_body` | Long Text |

### 2. Create the Shell Sequence

1. Go to **Engage → Sequences → New Sequence**
2. Name it exactly: **`AI Bespoke Send`**
3. Add a single **Automatic Email** step with:
   - **Subject:** `{{ai_email_subject}}`
   - **Body:**
     ```
     Hi {{#if first_name}}{{first_name}}{{#else}}there{{#endif}},

     {{ai_email_body}}

     — {{sender_first_name}}
     ```
   - **Wait time on step 1:** 0 minutes

### 3. Activate the Sequence

Click "Activate" on the sequence. It must be active for enrollment to work.

### 4. Verify Mailbox

Confirm at least one email mailbox is connected and not paused under **Settings → Email → Connected Accounts**.

The sending mailbox will be: `michael@rockeyvolunteer.com`

## Verification

After completing these steps, the sending-mcp will verify:
- The sequence "AI Bespoke Send" exists via API
- Both custom fields exist
- At least one active mailbox is connected
