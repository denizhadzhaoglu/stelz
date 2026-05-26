# Platform staff role

Any user signed in with a verified `@jackandai.com` email automatically has admin-like access to every brand in the system. No per-brand `brand_users` entries needed.

## Why it exists

The product is multi-tenant: customer brands operate independently with strict RLS isolation. But the JackandAI team needs to operate the platform itself — moderate detections during early days, debug a customer's data, onboard a new brand manually. Without a staff carve-out we'd be adding ourselves as `brand_users.role='admin'` on every brand, which is messy and pollutes customer team lists.

This role is the cross-tenant operator access. It does not replace per-brand membership for customers; it complements it.

## How it works

A SQL function `is_platform_staff()` returns true when:
- The caller's `auth.uid()` resolves to an `auth.users` row
- That row has `email_confirmed_at IS NOT NULL` (email verified)
- The email ends with `@jackandai.com` (strict lowercase match)

Two existing RLS helper functions are updated to include staff:
- `user_can_read_brand(brand_id)` → staff reads any brand
- `user_can_write_brand(brand_id)` → staff writes to any brand

Plus three additive `*_staff_all` policies cover tables that have their own qual (not via the helpers):
- `brands` → staff reads + writes any brand row
- `brand_users` → staff reads + writes any team membership
- `brand_invites` → staff reads + writes any invite
- `signup_leads` → staff reads + provisions any prospect

## What staff cannot do

- **Delete brands.** No DELETE policy added; PostgreSQL default-deny stays in force. Removing a customer's brand stays an explicit owner-only action.
- **Be the customer.** Staff is invisible-by-default in team UIs. Customers don't see "external admin from JackandAI" in their team list. (We may change this later for transparency when we have paying customers — see open question below.)
- **Bypass billing.** Staff can read subscriptions, but Stripe is the source of truth for billing state. Staff edits to subscriptions are operational, not financial.

## Who has it today

| Email | Verified | Staff |
|-------|----------|-------|
| meinte@jackandai.com | yes | yes (any future @jackandai.com email auto-qualifies) |

To onboard a new staff member: they sign up via the standard auth flow with their `@jackandai.com` email, verify the email, and they're in. No additional setup.

## Security considerations

- Email-domain check is strict (`lower(email) LIKE '%@jackandai.com'`).
- Email must be `email_confirmed_at NOT NULL` so a malicious actor can't squat with an unverified address.
- If JackandAI's domain ever expires or changes, ALL staff access disappears the moment new emails can't be verified — fail-safe behavior.
- The function is `SECURITY DEFINER` so it bypasses RLS on `auth.users` for the email lookup, but only returns boolean — no PII leak.

## Open questions

- **Make staff visible in customer team UIs?** Right now staff have access but don't appear in team lists. For a paying customer this might feel like surveillance — they have an external user with admin power they can't see. When we have our first non-design-partner customer, decide: full transparency (show as "JackandAI platform support · external") vs invisible (cleaner, customer focuses on their own team).
- **Staff audit log?** Currently no separate trail of which staff member edited what. As staff grows past 2 people, add a `staff_audit_log` table that records every write made via staff access.
- **Restricted staff scope?** Today every `@jackandai.com` email gets full admin everywhere. Later we may want tiered staff (read-only support agent vs admin), driven by a `platform_role` column on a `staff_users` table. Build when needed.

## Verifying staff access

After logging in with `meinte@jackandai.com`, you should be able to:
- Open `https://spotyourbrand.com/moderator.html?brand=stelz` and moderate STELZ detections
- Open the same with `?brand=spot-the-brand-demo` and moderate demo detections
- Open `?brand=<future-customer>` and operate there too
- Read every brand's data via the dashboard (`/?brand=<slug>`)
- Provision new signup leads via the admin tools

If a write silently fails (the toast says "Geen rechten op deze detection (RLS)") on your @jackandai.com account, that's a bug — staff should always have write access. Report.
