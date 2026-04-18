# Recovery Pack Authoring Guide

## Purpose

This guide explains how to add new interruption handling behavior without weakening the deterministic architecture.

The goal is not to make the runtime "think more."
The goal is to make common interruptions become reusable assets.

## Authoring Workflow

1. Reproduce the interruption.
2. Capture the visible texts, buttons, checkboxes, and dialogs that uniquely identify it.
3. Decide whether the interruption is:
   - global/common
   - product-specific
   - too risky for auto-recovery
4. Encode it as a `RecoveryRule`.
5. Add a focused test that proves both detection and action selection.

## Rule Design Checklist

Use a new rule only if the blocker is:

1. Common enough to justify reuse
2. Low-risk to clear automatically
3. Recognizable from a compact snapshot

Avoid adding a rule when:

1. The action is destructive
2. The page meaning is ambiguous
3. The correct decision depends on hidden business context

## Good Rule Examples

### Agreement checkbox before login

Signature:

1. Visible text mentions service agreement, privacy policy, or terms
2. A nearby checkbox is unchecked
3. A submit/send/login action is present

Action plan:

1. Check the agreement box
2. Retry the blocked button
3. Wait briefly

### Cookie/privacy banner

Signature:

1. Visible text mentions cookies or privacy choices
2. Banner buttons include accept, agree, allow, or continue

Action plan:

1. Click the least risky acceptance/close control
2. Wait briefly

### Lightweight notice dialog

Signature:

1. Short modal-like notice
2. Buttons such as later, close, got it, cancel, or not now

Action plan:

1. Click the low-risk dismiss control
2. Retry the interrupted step

## File Layout

Current recovery implementation:

1. Models: `D:\AI\AI_RPA\src\omniauto\recovery\models.py`
2. Policy: `D:\AI\AI_RPA\src\omniauto\recovery\policy.py`
3. Rules: `D:\AI\AI_RPA\src\omniauto\recovery\registry.py`
4. Fallback: `D:\AI\AI_RPA\src\omniauto\recovery\fallback.py`
5. Runtime manager: `D:\AI\AI_RPA\src\omniauto\recovery\manager.py`

## Action Whitelist

Prefer these actions:

1. `check_text`
2. `click_text`
3. `click_selector`
4. `press_key`
5. `wait`

If a new rule needs a new action type, treat that as an architecture change, not a normal content update.

## Testing Rule Packs

Every new rule should have:

1. One unit test for rule matching / plan output
2. One execution-level test when practical

Execution-level tests should use synthetic HTML where possible.
That makes them deterministic and avoids flaky dependence on third-party websites.

## Escalation Boundary

Do not auto-recover:

1. Payments
2. Deletes
3. Security-sensitive confirmations
4. Any action that could submit irreversible business data

Those cases should escalate or require an explicit higher-trust policy.
