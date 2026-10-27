# Soccer Team Points Tracker

A public, mobile-friendly Streamlit site for tracking player Win/Goal/Assist
points and leaderboards. Anyone with the link can view it; only editors
manually approved by the team owner can change anything.

**How authorization actually works:** `app.py` hides editor buttons from
people who aren't signed in or aren't approved, but that is only UI
polish. The real enforcement is in [`sql/schema.sql`](sql/schema.sql):
Postgres Row Level Security policies that check `auth.uid()` against the
`editor_allowlist` table on every insert/update/delete. Even if someone
calls the Supabase REST API directly, bypassing the Streamlit app
completely, those policies still apply. Streamlit's Python server handles
*interaction*; the database is the *authorization* layer.

## 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com), sign in, and click **New
   project**.
2. Pick an organization, name the project (e.g. `wsoc-point-tracker`), set a
   database password (save it somewhere safe — you likely won't need it
   again for this app, but you will if you ever connect directly to
   Postgres), and choose a region close to your team.
3. Wait for provisioning to finish (a couple of minutes).

## 2. Apply the schema

1. In the Supabase dashboard, open **SQL Editor**.
2. Open [`sql/schema.sql`](sql/schema.sql) from this repo, copy its entire
   contents, paste into a new query, and run it.
3. Confirm in **Table Editor** that `players`, `point_events`, and
   `editor_allowlist` all exist, and that each has a green "RLS enabled"
   badge.

The script is safe to re-run if you need to reapply it later.

## 3. Create editor accounts and approve them

There is **no public sign-up flow** in this app by design — you create
accounts and approve editors by hand.

1. In Supabase, go to **Authentication → Users → Add user** and create one
   user per editor (email + password). "Auto Confirm User" can stay
   checked for a simple internal tool like this.
2. Copy that user's **User UID** from the users list.
3. Go to **Table Editor → editor_allowlist → Insert row**, and set
   `user_id` to the UID you copied. That's it — that user can now edit.
4. To revoke editor access later, delete their row from `editor_allowlist`
   (their login still works, they just drop back to read-only).

Only you (via the dashboard) can do this. Ordinary editors have no way to
read or write `editor_allowlist` at all — that's enforced by RLS, not by
the app hiding a button.

## 4. Configure secrets

The app needs two values: your project's URL and its anon/public key.
Find both in Supabase under **Project Settings → API**.

**Local development** — copy the example file and fill it in:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_ANON_KEY = "your-anon-public-key"
```

`secrets.toml` is gitignored — never commit it. The anon key is meant to be
public-facing (it's what RLS exists to constrain), but there's no reason to
hardcode it in source either.

**Streamlit Community Cloud** — paste the same two keys into your app's
**Settings → Secrets** box (same TOML syntax as above) instead of uploading
a file.

Never put a Supabase **service role** key anywhere in this app. It bypasses
RLS entirely, which would defeat the whole point of this setup.

## 5. Install dependencies and run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL Streamlit prints. You should see the public Players and
Leaderboard tabs. Use the sidebar "Editor login" with one of the accounts
from step 3 to see the Manage Team tab appear.

## 6. Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (see note on git below if you're unsure how).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in, and
   click **New app**.
3. Point it at your GitHub repo, branch `master` (or `main`), and
   `app.py` as the entry point.
4. Add your secrets under **Advanced settings → Secrets** before (or right
   after) the first deploy.
5. Deploy. Future pushes to the branch auto-redeploy.

## 7. Share it

The deployed URL is public and read-only for anyone who opens it — no
account needed. Share it with the team. Only share editor
email/password credentials with people you actually want able to edit,
and only after adding them to `editor_allowlist` (step 3).

## 8. Backing up / exporting data

- **Table Editor** → select a table → **Export** lets you download CSV
  snapshots of `players` or `point_events` anytime.
- For a full database backup/restore, Supabase project settings include
  **Database → Backups** (scheduled backups on most plans, or you can run
  `pg_dump` against the connection string under **Project Settings →
  Database** for a manual export).

## 9. Running tests and checking RLS security

Unit tests (no database needed):

```bash
pytest tests/test_search.py tests/test_points.py
```

These cover search ranking, leaderboard ordering/ties, and category/name
validation.

Authorization/integration tests (`tests/test_authorization.py`) call the
Supabase REST API directly, bypassing the app, to prove RLS itself rejects
unauthorized writes. They need a **separate, dedicated test Supabase
project** (apply the same `sql/schema.sql` to it) — never point them at
your real team's project, since they insert and delete real rows. Create
one editor user (add to that test project's `editor_allowlist`) and one
plain, unapproved user, then set:

```bash
export SUPABASE_TEST_URL="https://your-test-project-ref.supabase.co"
export SUPABASE_TEST_ANON_KEY="your-test-anon-key"
export SUPABASE_TEST_EDITOR_EMAIL="editor@example.com"
export SUPABASE_TEST_EDITOR_PASSWORD="..."
export SUPABASE_TEST_NON_EDITOR_EMAIL="viewer@example.com"
export SUPABASE_TEST_NON_EDITOR_PASSWORD="..."
pytest tests/test_authorization.py
```

Without those variables set, this file's tests are skipped automatically
(you'll see `SKIPPED` in the pytest output, not a failure).

### Manual checklist (for things that don't automate well)

- [ ] Anonymous visitor can see active roster, search, and all four
      leaderboards without signing in.
- [ ] Anonymous/unapproved API calls to insert, update, or delete are
      rejected (covered by the automated tests above, but worth spot
      checking with `curl` against your real project too).
- [ ] Sign in as an approved editor → Manage Team tab appears → award/undo
      points, add/rename/deactivate/reactivate a player, award a team win.
- [ ] Sign in as a valid but unapproved account → stays read-only, with a
      message explaining why (no crash, no edit controls).
- [ ] Log out → edit controls disappear immediately.
- [ ] Open the site in two separate browsers; award a point in one, hit
      Refresh (or wait ~30s) in the other, confirm totals match.
- [ ] Close the browser tab entirely, reopen the URL — data is still there
      (it's in Supabase, not browser/session state).
- [ ] Rename and deactivate a player, then reactivate them — confirm their
      point history (totals) is unchanged throughout.
- [ ] Confirm `editor_allowlist` has no rows addable from the app UI or a
      direct API call, even by an existing editor.
- [ ] Confirm no Supabase **service role** key appears anywhere in the
      deployed app's code or secrets.

## A note on git

This project was initialized as its own git repository. If you're new to
git: `git add -A && git commit -m "..."` stages and commits your changes,
and `git push` (after `git remote add origin <your-github-url>` and
`git branch -M main` if you prefer that name) sends them to GitHub for
Streamlit Cloud to deploy from.

## Project layout

```text
wsoc-point-tracker/
├── app.py                   # Streamlit UI, role-aware rendering
├── database.py               # Supabase client and raw data access
├── auth.py                   # sign-in, sign-out, role checks
├── points.py                  # point operations and rankings
├── search.py                  # exact, partial, fuzzy matching
├── sql/
│   └── schema.sql            # schema + RLS policies + RPCs
├── tests/
│   ├── test_points.py
│   ├── test_search.py
│   └── test_authorization.py
├── .streamlit/
│   └── secrets.toml.example
├── requirements.txt
├── pytest.ini
├── .gitignore
└── README.md
```

## Known v1 limitations

- No CSV roster import yet (noted in the spec as optional/"later").
- No match/opponent tracking — team wins are awarded manually with no
  game record attached.
- No permanent player deletion — deactivate instead; history is preserved.
- Public refresh is a 30-second cache plus a manual Refresh button, not a
  live push — true real-time would need a polling/websocket component,
  which was left out to keep dependencies minimal.
