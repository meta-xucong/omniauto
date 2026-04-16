"""妗岄潰鑷姩鍖栵紙RPA 绾э級锛氭墦寮€ WPS 鏂囧瓧锛岃緭鍏ュ叆鍏氱敵璇蜂功锛屼繚瀛樺埌妗岄潰骞跺叧闂?

鏈剼鏈熀浜?`omniauto.skills.wps_automation.WPSWordAutomation`锛?鍏峰浠ヤ笅鍟嗕笟 RPA 鐗规€э細
- 闃插尽鎬х獥鍙ｇ劍鐐圭鐞嗭紙 AttachThreadInput + TOPMOST 锛?- 澶氭爣绛鹃〉鍏煎锛堣嚜鍔ㄧ偣鍑荤洰鏍囨爣绛撅級
- 鍓创鏉夸腑鏂囩矘璐达紙缁曡繃 WPS Qt+Chromium 缂栬緫鍖烘嫤鎴級
- 蹇嵎閿け璐ュ洖閫€锛團12 / 鑿滃崟鐐瑰嚮锛?- 淇濆瓨鍓嶈嚜鍔ㄦ竻鐞嗘棫鏂囦欢銆佷繚瀛樺悗鏂囦欢瀛樺湪鎬ч獙璇?- IME 鍊欓€夋妫€娴嬩笌鑷姩娑堥櫎
"""

import asyncio
import time
from pathlib import Path

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.skills.wps_automation import WPSWordAutomation, _create_blank_docx


WPS_EXE = r"C:\Users\鍏拌惤钀界殑鏈湰\AppData\Local\Kingsoft\WPS Office\12.1.0.25865\office6\wps.exe"
SAVE_PATH = r"C:\Users\鍏拌惤钀界殑鏈湰\Desktop\鍏ュ厷鐢宠涔?docx"
# 浣跨敤甯︽椂闂存埑鐨勪复鏃舵枃浠跺悕锛岄伩鍏嶈涔嬪墠鏈叧闂殑 WPS 杩涚▼閿佸畾
TEST_ARTIFACT_DIR = Path("test_artifacts/manual_wps")
TEMP_DOCX = TEST_ARTIFACT_DIR / f"temp_party_app_{int(time.time())}.docx"

APPLICATION_TEXT = (
    "鍏ュ厷鐢宠涔n\n"
    "鏁埍鐨勫厷缁勭粐锛歕n\n"
    "    鎴戝織鎰垮姞鍏ヤ腑鍥藉叡浜у厷锛屾効鎰忎负鍏变骇涓讳箟浜嬩笟濂嬫枟缁堣韩銆?
    "涓浗鍏变骇鍏氭槸涓浗宸ヤ汉闃剁骇鐨勫厛閿嬮槦锛屽悓鏃舵槸涓浗浜烘皯鍜屼腑鍗庢皯鏃忕殑鍏堥攱闃燂紝"
    "鏄腑鍥界壒鑹茬ぞ浼氫富涔変簨涓氱殑棰嗗鏍稿績銆俓n\n"
    "    鎴戜箣鎵€浠ヨ鍔犲叆涓浗鍏变骇鍏氾紝鏄洜涓烘垜娣变俊鍏变骇涓讳箟浜嬩笟鐨勫繀鐒舵垚鍔燂紝"
    "娣变俊鍙湁绀句細涓讳箟鎵嶈兘鏁戜腑鍥斤紝鍙湁绀句細涓讳箟鎵嶈兘鍙戝睍涓浗銆俓n\n"
    "    璇峰厷缁勭粐鍦ㄥ疄璺典腑鑰冮獙鎴戯紒\n\n"
    "姝よ嚧\n"
    "鏁ぜ锛乗n\n"
    "鐢宠浜猴細XXX\n"
    "2026骞?鏈?3鏃n"
)


async def step_open_wps(ctx: TaskContext) -> StepResult:
    import uuid
    TEST_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = TEMP_DOCX
    for _ in range(3):
        try:
            _create_blank_docx(str(temp_path))
            break
        except PermissionError:
            temp_path = temp_path.parent / f"temp_party_app_{uuid.uuid4().hex[:8]}.docx"
    else:
        return StepResult(success=False, error=f"鏃犳硶鍒涘缓涓存椂鏂囨。锛堟枃浠惰閿佸畾锛? {temp_path}")

    wps = WPSWordAutomation(WPS_EXE)
    ctx.visual_state["wps"] = wps
    ok = wps.open_document(str(temp_path))
    if not ok:
        return StepResult(success=False, error="WPS 鏂囧瓧鍚姩鎴栫獥鍙ｅ畾浣嶅け璐?)
    return StepResult(success=True, data="WPS 鏂囧瓧宸插惎鍔ㄥ苟鑱氱劍")


async def step_type_application(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 鑷姩鍖栧疄渚嬫湭鍒濆鍖?)
    ok = wps.type_text(APPLICATION_TEXT, clear_existing=True)
    if not ok:
        return StepResult(success=False, error="鏂囨湰杈撳叆澶辫触锛堝彲鑳芥槸鐒︾偣涓㈠け鎴?IME 寮傚父锛?)
    return StepResult(success=True, data="宸茶緭鍏ュ叆鍏氱敵璇蜂功")


async def step_save_file(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 鑷姩鍖栧疄渚嬫湭鍒濆鍖?)

    # 涓绘柟妗堬細F12 / Ctrl+Shift+S 鎵撳紑鍙﹀瓨涓哄璇濇 + 绮樿创鏂囦欢鍚?    ok = wps.save_as(SAVE_PATH, overwrite=True)
    if not ok:
        # 鍥為€€鏂规锛氳彍鍗曟爮鐐瑰嚮淇濆瓨
        ok = wps.save_via_menu(SAVE_PATH)
    if not ok:
        return StepResult(success=False, error="淇濆瓨澶辫触锛堟枃浠舵湭鐢熸垚鎴栬鐩栨彁绀烘湭澶勭悊锛?)
    return StepResult(success=True, data=f"宸蹭繚瀛樺埌 {SAVE_PATH}")


async def step_close_wps(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 鑷姩鍖栧疄渚嬫湭鍒濆鍖?)
    wps.close_document(save_before_close=False)
    return StepResult(success=True, data="宸插彂閫佸叧闂寚浠?)


workflow = Workflow(task_id="desktop_wps_word_visual")
workflow.add_step(AtomicStep("open_wps", step_open_wps, lambda r: r.success))
workflow.add_step(AtomicStep("type_application", step_type_application, lambda r: r.success))
workflow.add_step(AtomicStep("save_file", step_save_file, lambda r: r.success))
workflow.add_step(AtomicStep("close_wps", step_close_wps, lambda r: r.success))


if __name__ == "__main__":
    ctx = TaskContext(task_id="desktop_wps_word_visual")
    result = asyncio.run(workflow.run(ctx))
    print(f"Workflow result: {result}")
    for sid, out in ctx.outputs.items():
        print(f"  {sid}: {out}")


