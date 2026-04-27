"""Browser recovery manager."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from playwright.async_api import Page

from .fallback import BrowserRecoveryFallback, HeuristicRecoveryFallback
from .models import (
    BrowserCheckboxSnapshot,
    BrowserInterruptionSnapshot,
    RecoveryAction,
    RecoveryAttemptResult,
)
from .policy import RecoveryPolicy
from .registry import BrowserRecoveryRegistry, VERIFICATION_CHALLENGE_KEYWORDS


class BrowserRecoveryManager:
    """Runtime coordinator for browser interruption recovery."""

    def __init__(
        self,
        page_getter: Callable[[], Optional[Page]],
        registry: Optional[BrowserRecoveryRegistry] = None,
        policy: Optional[RecoveryPolicy] = None,
        fallback: Optional[BrowserRecoveryFallback] = None,
        artifact_dir_getter: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._page_getter = page_getter
        self.registry = registry or BrowserRecoveryRegistry.default()
        self.policy = policy or RecoveryPolicy()
        self.fallback = fallback or HeuristicRecoveryFallback()
        self._artifact_dir_getter = artifact_dir_getter
        self._in_recovery = False
        self._signature_hits: dict[str, int] = {}
        self._total_cycles = 0
        self._attempt_counter = 0

    async def collect_snapshot(self) -> Optional[BrowserInterruptionSnapshot]:
        page = self._page_getter()
        if page is None:
            return None

        visible_texts: list[str] = []
        buttons: list[str] = []
        checkboxes: list[BrowserCheckboxSnapshot] = []
        dialogs: list[str] = []

        for frame in list(page.frames):
            try:
                data = await frame.evaluate(
                    """
                    () => {
                        const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.visibility !== 'hidden'
                                && style.display !== 'none'
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const isManualHandoffOverlay = (el) => !!el?.closest?.(
                            '#__omniauto_manual_handoff_banner, #__omniauto_manual_handoff_modal'
                        );

                        const textEls = Array.from(document.querySelectorAll('body *'))
                            .filter((el) => isVisible(el) && !isManualHandoffOverlay(el))
                            .slice(0, 400);

                        const texts = [];
                        for (const el of textEls) {
                            const text = normalize(el.innerText || el.textContent || '');
                            if (!text || text.length < 2 || text.length > 120) continue;
                            texts.push(text);
                            if (texts.length >= 60) break;
                        }

                        const buttons = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"]'))
                            .filter((el) => isVisible(el) && !isManualHandoffOverlay(el))
                            .map((el) => normalize(el.innerText || el.value || el.getAttribute('aria-label') || ''))
                            .filter(Boolean)
                            .slice(0, 30);

                        const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"], input[type="radio"]'))
                            .filter((input) => !isManualHandoffOverlay(input))
                            .map((input) => {
                                const label = normalize(
                                    input.closest('label')?.innerText
                                    || input.parentElement?.innerText
                                    || input.parentElement?.parentElement?.innerText
                                    || ''
                                );
                                return {
                                    label,
                                    checked: !!input.checked || input.getAttribute('aria-checked') === 'true',
                                };
                            })
                            .filter((item) => item.label)
                            .slice(0, 20);

                        const dialogs = Array.from(document.querySelectorAll('[role="dialog"], dialog, .modal, .popup, .popover'))
                            .filter((el) => isVisible(el) && !isManualHandoffOverlay(el))
                            .map((el) => normalize(el.innerText || ''))
                            .filter(Boolean)
                            .slice(0, 10);

                        return {
                            title: document.title || '',
                            url: location.href || '',
                            texts,
                            buttons,
                            checkboxes,
                            dialogs,
                        };
                    }
                    """
                )
            except Exception:
                continue

            visible_texts.extend(data.get("texts", []))
            buttons.extend(data.get("buttons", []))
            dialogs.extend(data.get("dialogs", []))
            checkboxes.extend(
                BrowserCheckboxSnapshot(
                    label=item.get("label", ""),
                    checked=bool(item.get("checked", False)),
                )
                for item in data.get("checkboxes", [])
                if item.get("label")
            )

        return BrowserInterruptionSnapshot(
            url=page.url,
            title=await page.title(),
            visible_texts=_unique_preserve_order(visible_texts)[:60],
            buttons=_unique_preserve_order(buttons)[:30],
            checkboxes=_dedupe_checkboxes(checkboxes)[:20],
            dialogs=_unique_preserve_order(dialogs)[:10],
        )

    async def recover(
        self,
        trigger: str,
        error: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> RecoveryAttemptResult:
        if self._in_recovery:
            return RecoveryAttemptResult(handled=False, trigger=trigger, error="recovery_in_progress")

        snapshot = await self.collect_snapshot()
        if snapshot is None:
            result = RecoveryAttemptResult(handled=False, trigger=trigger, error="page_unavailable")
            await self._write_attempt_artifacts(result)
            return result

        if _looks_like_verification_challenge(snapshot, error):
            if self._total_cycles >= self.policy.max_total_cycles:
                result = RecoveryAttemptResult(
                    handled=False,
                    trigger=trigger,
                    before=snapshot,
                    after=snapshot,
                    source="rule_registry",
                    error="recovery_budget_exhausted",
                )
                await self._write_attempt_artifacts(result)
                return result
            self._total_cycles += 1
            if self.policy.stop_on_risk_pages and not self.policy.wait_for_manual_handoff:
                result = RecoveryAttemptResult(
                    handled=False,
                    trigger=trigger,
                    before=snapshot,
                    after=snapshot,
                    source="manual_handoff",
                    error=error,
                    handoff_requested=True,
                    handoff_reason="verification_challenge_detected",
                )
                await self._write_attempt_artifacts(result)
                return result
            return await self._wait_for_manual_resolution(
                trigger=trigger,
                snapshot=snapshot,
                reason="verification_challenge_detected",
                error=error,
            )

        signature = _snapshot_signature(snapshot)
        if self._signature_hits.get(signature, 0) >= self.policy.max_repeat_per_signature:
            result = RecoveryAttemptResult(
                handled=False,
                trigger=trigger,
                before=snapshot,
                error="recovery_signature_repeat_limit",
            )
            await self._write_attempt_artifacts(result)
            return result

        self._in_recovery = True
        executed: list[RecoveryAction] = []
        matched_names: list[str] = []
        source = "rule_registry"
        try:
            candidate_actions: list[RecoveryAction] = []
            for rule in self.registry.match(snapshot, trigger)[: self.policy.max_rules_per_cycle]:
                plan = rule.planner(snapshot)
                allowed_actions = [action for action in plan.actions if self.policy.allows(action)]
                if not allowed_actions:
                    continue
                matched_names.append(rule.name)
                remaining = self.policy.max_actions_per_cycle - len(candidate_actions)
                if remaining <= 0:
                    break
                candidate_actions.extend(allowed_actions[:remaining])
                if len(candidate_actions) >= self.policy.max_actions_per_cycle:
                    break

            if not candidate_actions and self.fallback is not None:
                plan = await self.fallback.plan(snapshot, self.policy.allowed_action_names(), trigger)
                if plan is not None:
                    fallback_actions = [action for action in plan.actions if self.policy.allows(action)]
                    if fallback_actions:
                        source = plan.source
                        matched_names.append(plan.name)
                        candidate_actions.extend(fallback_actions[: self.policy.max_actions_per_cycle])

            if candidate_actions and self._total_cycles >= self.policy.max_total_cycles:
                result = RecoveryAttemptResult(
                    handled=False,
                    trigger=trigger,
                    before=snapshot,
                    after=snapshot,
                    source=source,
                    error="recovery_budget_exhausted",
                )
                await self._write_attempt_artifacts(result)
                return result

            for action in candidate_actions:
                if len(executed) >= self.policy.max_actions_per_cycle:
                    break
                if await self._apply_action(action):
                    executed.append(action)
                    await asyncio.sleep(0.3)

            after = await self.collect_snapshot() if executed else snapshot
            if executed:
                self._total_cycles += 1
                self._signature_hits[signature] = self._signature_hits.get(signature, 0) + 1
            result = RecoveryAttemptResult(
                handled=bool(executed),
                trigger=trigger,
                matched_rules=matched_names,
                executed_actions=executed,
                before=snapshot,
                after=after,
                source=source,
                error=error,
            )
            if executed or matched_names or error or self.policy.count_noop_cycles:
                await self._write_attempt_artifacts(result)
            return result
        finally:
            self._in_recovery = False

    async def _apply_action(self, action: RecoveryAction) -> bool:
        page = self._page_getter()
        if page is None:
            return False

        if action.action_type == "click_text":
            return await self._click_text(page, action.target)
        if action.action_type == "check_text":
            return await self._check_text(page, action.target)
        if action.action_type == "click_selector":
            return await self._click_selector(page, action.target)
        if action.action_type == "press_key":
            await page.keyboard.press(action.target)
            return True
        if action.action_type == "wait":
            await asyncio.sleep(float(action.value or 0.5))
            return True
        return False

    async def _click_selector(self, page: Page, selector: str) -> bool:
        for frame in list(page.frames):
            try:
                locator = frame.locator(selector).first
                await locator.wait_for(state="visible", timeout=800)
                await locator.click()
                return True
            except Exception:
                continue
        return False

    async def _click_text(self, page: Page, text: str) -> bool:
        if not text:
            return False
        for frame in list(page.frames):
            try:
                locator = frame.get_by_text(text, exact=False).first
                await locator.wait_for(state="visible", timeout=800)
                await locator.click()
                return True
            except Exception:
                pass
            try:
                clicked = await frame.evaluate(
                    """
                    (targetText) => {
                        const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                        const isVisible = (el) => {
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.visibility !== 'hidden'
                                && style.display !== 'none'
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const nodes = Array.from(document.querySelectorAll('button, a, label, span, div, input[type="button"], input[type="submit"], [role="button"]'));
                        const target = nodes.find((node) => {
                            if (!isVisible(node)) return false;
                            const text = normalize(node.innerText || node.textContent || node.value || '');
                            return text && text.includes(targetText);
                        });
                        if (!target) return false;
                        target.click();
                        return true;
                    }
                    """,
                    text,
                )
                if clicked:
                    return True
            except Exception:
                continue
        return False

    async def _check_text(self, page: Page, text: str) -> bool:
        if not text:
            return False
        for frame in list(page.frames):
            try:
                changed = await frame.evaluate(
                    """
                    (targetText) => {
                        const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                        const boxes = Array.from(document.querySelectorAll('input[type="checkbox"], input[type="radio"]'));
                        for (const box of boxes) {
                            const labelText = normalize(
                                box.closest('label')?.innerText
                                || box.parentElement?.innerText
                                || box.parentElement?.parentElement?.innerText
                                || ''
                            );
                            if (!labelText || !labelText.includes(targetText)) continue;
                            if (box.checked || box.getAttribute('aria-checked') === 'true') return true;
                            const label = box.closest('label');
                            if (label) {
                                label.click();
                            } else {
                                box.click();
                            }
                            return true;
                        }
                        return false;
                    }
                    """,
                    text,
                )
                if changed:
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_manual_resolution(
        self,
        trigger: str,
        snapshot: BrowserInterruptionSnapshot,
        reason: str,
        error: Optional[str] = None,
    ) -> RecoveryAttemptResult:
        deadline = asyncio.get_running_loop().time() + self.policy.manual_handoff_timeout_sec
        self._total_cycles += 1
        result = RecoveryAttemptResult(
            handled=False,
            trigger=trigger,
            before=snapshot,
            after=snapshot,
            source="manual_handoff",
            error=error,
            handoff_requested=True,
            handoff_reason=reason,
        )
        await self._write_attempt_artifacts(result)

        prompt_ack_seen = False
        try:
            while asyncio.get_running_loop().time() < deadline:
                page = self._page_getter()
                remaining_sec = max(0, int(deadline - asyncio.get_running_loop().time()))
                if page is not None:
                    await self._render_manual_handoff_prompt(
                        page,
                        reason=reason,
                        remaining_sec=remaining_sec,
                        resolved=False,
                        show_modal=not prompt_ack_seen,
                    )
                    prompt_ack_seen = True

                await asyncio.sleep(self.policy.manual_handoff_poll_interval_sec)
                after = await self.collect_snapshot()
                if after is None:
                    continue
                if not _looks_like_verification_challenge(after, None):
                    page = self._page_getter()
                    while asyncio.get_running_loop().time() < deadline:
                        remaining_sec = max(0, int(deadline - asyncio.get_running_loop().time()))
                        if page is not None:
                            await self._render_manual_handoff_prompt(
                                page,
                                reason=reason,
                                remaining_sec=remaining_sec,
                                resolved=True,
                                show_modal=False,
                            )
                            if await self._manual_handoff_continue_clicked(page):
                                await self._clear_manual_handoff_prompt(page)
                                result.handled = True
                                result.after = after
                                await self._write_attempt_artifacts(result)
                                return result
                        await asyncio.sleep(self.policy.manual_handoff_poll_interval_sec)
                        after = await self.collect_snapshot()
                        if after is None:
                            continue
                        if _looks_like_verification_challenge(after, None):
                            break
                        page = self._page_getter()
        finally:
            page = self._page_getter()
            if page is not None:
                await self._clear_manual_handoff_prompt(page)

        result.error = "manual_handoff_timeout"
        await self._write_attempt_artifacts(result)
        return result

    async def _render_manual_handoff_prompt(
        self,
        page: Page,
        *,
        reason: str,
        remaining_sec: int,
        resolved: bool,
        show_modal: bool,
    ) -> None:
        try:
            await page.evaluate(
                """
                (payload) => {
                    const state = window.__omniautoManualHandoff || {};
                    state.reason = payload.reason;
                    state.remainingSec = payload.remainingSec;
                    state.resolved = payload.resolved;
                    state.continueClicked = payload.resolved ? !!state.continueClicked : false;
                    window.__omniautoManualHandoff = state;

                    const ensureBanner = () => {
                        let host = document.getElementById('__omniauto_manual_handoff_banner');
                        if (!host) {
                            host = document.createElement('div');
                            host.id = '__omniauto_manual_handoff_banner';
                            host.style.cssText = [
                                'position:fixed',
                                'left:50%',
                                'bottom:16px',
                                'transform:translateX(-50%)',
                                'z-index:2147483647',
                                'width:min(920px, calc(100vw - 32px))',
                                'pointer-events:none',
                                'font-family:Segoe UI, Microsoft YaHei, sans-serif'
                            ].join(';');

                            const card = document.createElement('div');
                            card.id = '__omniauto_manual_handoff_banner_card';
                            card.style.cssText = [
                                'pointer-events:auto',
                                'background:rgba(0,0,0,0.92)',
                                'color:#fff',
                                'border:1px solid rgba(255,255,255,0.18)',
                                'border-radius:12px',
                                'padding:16px 18px',
                                'box-shadow:0 16px 40px rgba(0,0,0,0.45)',
                                'display:flex',
                                'gap:16px',
                                'align-items:center',
                                'justify-content:space-between'
                            ].join(';');

                            const textWrap = document.createElement('div');
                            textWrap.style.cssText = 'flex:1; min-width:0;';

                            const title = document.createElement('div');
                            title.id = '__omniauto_manual_handoff_title';
                            title.style.cssText = 'font-size:16px; font-weight:700; margin-bottom:6px;';
                            textWrap.appendChild(title);

                            const body = document.createElement('div');
                            body.id = '__omniauto_manual_handoff_body';
                            body.style.cssText = 'font-size:13px; line-height:1.55; color:rgba(255,255,255,0.88);';
                            textWrap.appendChild(body);

                            const timer = document.createElement('div');
                            timer.id = '__omniauto_manual_handoff_timer';
                            timer.style.cssText = 'font-size:12px; color:#ffd27d; margin-top:8px;';
                            textWrap.appendChild(timer);

                            const button = document.createElement('button');
                            button.id = '__omniauto_manual_handoff_continue';
                            button.type = 'button';
                            button.textContent = '已处理，继续任务';
                            button.style.cssText = [
                                'border:none',
                                'border-radius:10px',
                                'padding:10px 16px',
                                'background:#f97316',
                                'color:#fff',
                                'font-size:13px',
                                'font-weight:700',
                                'cursor:pointer',
                                'white-space:nowrap'
                            ].join(';');
                            button.onclick = () => {
                                const current = window.__omniautoManualHandoff || {};
                                current.continueClicked = true;
                                current.clickedAt = Date.now();
                                window.__omniautoManualHandoff = current;
                            };

                            card.appendChild(textWrap);
                            card.appendChild(button);
                            host.appendChild(card);
                            document.body.appendChild(host);
                        }
                        return host;
                    };

                    const ensureModal = () => {
                        let modal = document.getElementById('__omniauto_manual_handoff_modal');
                        if (!modal) {
                            modal = document.createElement('div');
                            modal.id = '__omniauto_manual_handoff_modal';
                            modal.style.cssText = [
                                'position:fixed',
                                'inset:0',
                                'z-index:2147483646',
                                'display:flex',
                                'align-items:flex-start',
                                'justify-content:center',
                                'padding-top:24px',
                                'pointer-events:none',
                                'background:transparent',
                                'font-family:Segoe UI, Microsoft YaHei, sans-serif'
                            ].join(';');

                            const panel = document.createElement('div');
                            panel.style.cssText = [
                                'width:min(560px, calc(100vw - 40px))',
                                'background:#111827',
                                'color:#fff',
                                'border-radius:16px',
                                'padding:22px 22px 18px',
                                'box-shadow:0 24px 64px rgba(0,0,0,0.45)',
                                'border:1px solid rgba(255,255,255,0.12)',
                                'pointer-events:auto'
                            ].join(';');

                            const title = document.createElement('div');
                            title.textContent = '检测到风控/验证，等待人工处理';
                            title.style.cssText = 'font-size:18px; font-weight:700; margin-bottom:10px;';

                            const body = document.createElement('div');
                            body.innerHTML = 'OmniAuto 已暂停当前步骤。<br>请先手动完成滑块/登录/验证。这个提示卡片不会阻塞页面操作；完成后点击页面底部黑色提示条中的“已处理，继续任务”。';
                            body.style.cssText = 'font-size:14px; line-height:1.7; color:rgba(255,255,255,0.88); margin-bottom:16px;';

                            const close = document.createElement('button');
                            close.type = 'button';
                            close.textContent = '我知道了，去处理';
                            close.style.cssText = [
                                'border:none',
                                'border-radius:10px',
                                'padding:10px 16px',
                                'background:#f97316',
                                'color:#fff',
                                'font-size:13px',
                                'font-weight:700',
                                'cursor:pointer'
                            ].join(';');
                            close.onclick = () => modal.remove();

                            panel.appendChild(title);
                            panel.appendChild(body);
                            panel.appendChild(close);
                            modal.appendChild(panel);
                            document.body.appendChild(modal);
                        }
                    };

                    ensureBanner();
                    const titleEl = document.getElementById('__omniauto_manual_handoff_title');
                    const bodyEl = document.getElementById('__omniauto_manual_handoff_body');
                    const timerEl = document.getElementById('__omniauto_manual_handoff_timer');
                    const buttonEl = document.getElementById('__omniauto_manual_handoff_continue');

                    if (payload.resolved) {
                        titleEl.textContent = '验证状态已恢复，等待你确认继续';
                        bodyEl.textContent = '请确认刚才的人工操作已经完成，然后点击右侧“已处理，继续任务”，自动化会从当前步骤继续。';
                        buttonEl.disabled = false;
                        buttonEl.style.opacity = '1';
                    } else {
                        titleEl.textContent = '检测到风控/验证页面，自动化已暂停';
                        bodyEl.textContent = '请先手动完成当前页面的验证、登录或安全检查。完成后回到本页，点击右侧“已处理，继续任务”。';
                        buttonEl.disabled = false;
                        buttonEl.style.opacity = '1';
                    }

                    const mins = Math.floor(payload.remainingSec / 60);
                    const secs = payload.remainingSec % 60;
                    timerEl.textContent = `最多等待 ${mins} 分 ${secs.toString().padStart(2, '0')} 秒；超时后将自动停止当前等待并进入收口逻辑。`;

                    if (payload.showModal) {
                        ensureModal();
                    }
                }
                """,
                {
                    "reason": reason,
                    "remainingSec": remaining_sec,
                    "resolved": resolved,
                    "showModal": show_modal,
                },
            )
        except Exception:
            return

    async def _manual_handoff_continue_clicked(self, page: Page) -> bool:
        try:
            return bool(
                await page.evaluate(
                    "() => !!(window.__omniautoManualHandoff && window.__omniautoManualHandoff.continueClicked)"
                )
            )
        except Exception:
            return False

    async def _clear_manual_handoff_prompt(self, page: Page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                    const ids = [
                        '__omniauto_manual_handoff_banner',
                        '__omniauto_manual_handoff_modal',
                    ];
                    for (const id of ids) {
                        document.getElementById(id)?.remove();
                    }
                    try {
                        delete window.__omniautoManualHandoff;
                    } catch (err) {
                        window.__omniautoManualHandoff = undefined;
                    }
                }
                """
            )
        except Exception:
            return

    def _artifact_root(self) -> Optional[Path]:
        if self._artifact_dir_getter is None:
            return None
        raw = self._artifact_dir_getter()
        if not raw:
            return None
        return Path(raw) / "recovery"

    async def _write_attempt_artifacts(self, result: RecoveryAttemptResult) -> None:
        root = self._artifact_root()
        if root is None:
            return

        root.mkdir(parents=True, exist_ok=True)
        self._attempt_counter += 1
        attempt_id = f"{self._attempt_counter:04d}_{result.trigger}"
        result.attempt_id = attempt_id
        result.artifact_dir = str(root)

        payload = result.to_dict()
        payload["timestamp"] = datetime.now().isoformat(timespec="seconds")
        (root / f"{attempt_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        page = self._page_getter()
        if page is None:
            return
        try:
            await page.screenshot(path=str(root / f"{attempt_id}.png"), full_page=True)
        except Exception:
            pass


def _unique_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_checkboxes(values: list[BrowserCheckboxSnapshot]) -> list[BrowserCheckboxSnapshot]:
    result: list[BrowserCheckboxSnapshot] = []
    seen: set[tuple[str, bool]] = set()
    for item in values:
        key = (item.label.strip(), item.checked)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _snapshot_signature(snapshot: BrowserInterruptionSnapshot) -> str:
    text = "|".join(
        [
            snapshot.url,
            snapshot.title,
            *snapshot.buttons[:10],
            *(item.label for item in snapshot.checkboxes[:10]),
            *snapshot.dialogs[:5],
        ]
    )
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _looks_like_verification_challenge(snapshot: BrowserInterruptionSnapshot, error: Optional[str]) -> bool:
    blob = snapshot.text_blob()
    if any(token.lower() in blob for token in VERIFICATION_CHALLENGE_KEYWORDS):
        return True
    if error and any(token.lower() in error.lower() for token in VERIFICATION_CHALLENGE_KEYWORDS):
        return True
    return False
