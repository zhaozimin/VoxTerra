# tests/
> L2 | 父级: ../CLAUDE.md

行为锚点：把不依赖音频/UI 的核心纯逻辑钉死。改代码先跑这里、绿了再打包，终结「每改一处就重打包验证」。

## 成员清单
- `test_core.py`: 标准库 `unittest` 套件(不引 pytest)。覆盖 `update_check`(版本解析/比较)、
  `model_fetch`(四态状态机 `model_status_key`、`model_ready` 体积门槛、`download_model` 完整性校验)、
  `i18n`(三语键齐全 + 关键文案)、关键词窗 `Cmd+V` 粘贴(macOS+pyobjc 才跑，否则跳过)。

## 运行
```
~/voicelog-venv/bin/python -m unittest tests.test_core -v
```

法则: 只测纯逻辑(import 无重副作用)·跨平台用例自动跳过·新增核心逻辑必须配锚点测试。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
