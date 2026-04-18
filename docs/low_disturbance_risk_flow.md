# Low-Disturbance Risk Flow

## Goal

Keep automation successful with the fewest possible site-visible actions.

The system now prefers:
1. fewer retries
2. fewer page hops
3. earlier handoff on login / verification / punish pages
4. partial deliverables over aggressive recovery

## Policy

### Normal UI issues
These can be handled automatically:
1. cookie banners
2. agreement checkboxes
3. low-risk popups
4. focus loss
5. benign close / later / skip dialogs

### Risk boundary pages
These are not auto-solved:
1. slider challenges
2. punish pages
3. login verification
4. captcha pages
5. identity / safety verification pages

When any of the above appears, the flow now:
1. stops immediately
2. writes artifacts and handoff metadata
3. preserves the current browser profile
4. resumes only after the user clears the boundary

## AI role

AI is used to manage the flow around risk, not to break the risk boundary itself.

AI can:
1. classify the current page type
2. decide whether to auto-recover or stop
3. write handoff context
4. resume the workflow from the correct point after manual completion

AI does not:
1. brute-force slider challenges
2. spam refresh / retry loops
3. keep probing punish pages
4. attempt repeated login-verification clicks

## Sensitive-site strategy

For 1688-like flows, the default strategy is now:
1. warm up once
2. open the search page once
3. settle the session after manual verification
4. scrape list pages first
5. enrich only a very small number of detail pages
6. stop detail enrichment immediately if risk returns
7. always emit a partial report if list data already exists

## Recovery budget behavior

The recovery budget no longer counts no-op checks by default.
Only real recovery actions or explicit handoff cycles count toward the budget.

This prevents normal `before_goto` / `before_wait_for_selector` inspections from exhausting recovery capacity.
