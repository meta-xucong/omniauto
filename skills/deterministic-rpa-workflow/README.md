# deterministic-rpa-workflow

这是给用户看的说明入口。

## 作用

把复杂浏览器/RPA任务拆成确定性的 Workflow + AtomicStep，
避免运行时让 AI 临场“想怎么点、怎么抓”。

## 真正生效的运行时位置

- `.agents/skills/deterministic-rpa-workflow/`

## 为什么这里不是运行时目录

因为运行时目录需要遵守 AI 工具链的约定；
这里保留一个可读入口，是为了让项目结构更直观。
