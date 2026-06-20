# voicelog/
> L2 | 父级: ../CLAUDE.md

应用本体：一个常驻菜单栏进程，把贴身麦的语音实时切句、过门控、本地转写、写进当天 Markdown。音频绝不落盘。

## 成员清单
- `voicelog_menubar.py`: 主程序与唯一进程。采集(sounddevice) → 切句(silero VADIterator) → **转写前三道门**(时长/能量近场/声纹) → 转写(mlx-whisper large-v3) → 复读+水印过滤 → 专名纠错 → 按时区写当天笔记(外置盘掉线回退内置)。rumps 菜单栏：计数/滤除数、暂停、注册声音、声纹门开关、时区、保存位置、打开笔记。
- `voicelog_win.py`: **Windows/跨平台托盘版入口**(与 macOS 的 voicelog_menubar.py 对等)。同构管线
  (采集→VAD→三道门→转写→过滤→写盘)+ 掉线自愈;转写注入 `transcribe_fw`,托盘用 pystray,无弹窗 UI
  (设置改 config.yaml,声纹注册走托盘+系统通知)。数据落 `%APPDATA%\VoiceLog`。复用 speaker/i18n。
- `transcribe_fw.py`: faster-whisper(CTranslate2) 转写封装,接口与 mlx_whisper.transcribe 对齐(吃 16k
  float32,吐文本)。有 N 卡 cuda/float16,否则 cpu/int8。Windows 端的转写引擎,亦可在 Mac 验证。
- `model_fetch.py`: 跨平台「模型获取」中枢(mac/win 共用)。**绕开 HF/镜像,直接从本项目 GitHub Release
  下载模型 zip**(国内可达),带进度回调、原子解压;`model_ready` 判本地是否就绪。config 模型项写 `auto`
  即托管模式(放 …/VoiceLog/models)。是「三层模型兜底」的第一层(应用内一键下)。`model_status_key()`
  把「下载中/已就绪/托管缺失/直连缺失」四态收敛成纯函数(mac/win 共用,可单测),驱动菜单常显的模型状态行。
- `update_check.py`: 跨平台「更新提示」中枢。启动后台查 GitHub Releases 最新正式版,`is_newer` 纯函数比版本号;
  有新版则菜单显示「🆕 有新版本 — 点此更新」跳下载页。**只查不装**,零签名/重启风险。mac/win 共用。
- `speaker.py`: 声纹门控子模块。`SpeakerGate` 用 ECAPA-TDNN(speechbrain) 把语音映射成 192 维音色指纹，注册机主质心后逐句算余弦相似度裁决「是不是机主」。懒加载、fail-open(未注册/故障一律放行)、附「提取质量」自一致性指标。
- `enroll_ui.py`: 声纹注册 UI 面(PyObjC/Cocoa)。`EnrollWindow` 两阶段：须知页(本地/隐私说明+开始按钮，不录音)→点开始→朗读页(句子+进度条)。纯展示层，采集逻辑在主文件 `Recorder.enroll`(质量驱动)，进度由 rumps.Timer 喂。
- `replace_ui.py`: 关键词管理 UI 面(PyObjC/Cocoa，**模态**——无 Dock 进程唯有模态窗口能稳拿键盘焦点)。`ReplaceWindow.run_modal()` 返回编辑后的文本，主文件 `parse_corrections`/`write_corrections` 解析为「精确纠错 rules(`错=正`) + 识别词库 terms(单写目标词，注入 prompt)」并写回 config。
- `i18n.py`: 多语言中枢(中/英/日)。**界面语言**(UI 文案+注册文案,config `ui_language`) 与 **主语言**(=whisper 转写语言,config `primary_language`) **解耦**；**辅语言**(`secondary_language`)注入 initial_prompt 强化中英混说偏置。菜单栏三子菜单独立切换。
- `ui_common.py`: 各原生窗口公共底座。`KeyWindow`(模态窗基类：LSUIElement 无主菜单致标准编辑快捷键失效，在窗口层拦截 Cmd+C/V/X/A/Z 转发焦点文本框) + `BtnTarget`(按钮回调桥) + `make_label`/`make_rich_label`(标签) + `push_regular`/`pop_regular`(激活策略引用计数：开窗变前台、计数归零回无 Dock)，被 enroll_ui / replace_ui 共用。
- `config.yaml`: 运行配置(本机实际值)。模型路径、设备、时区、术语偏置、纠错表、**三道门阈值**、回退目录。
- `config.example.yaml`: 配置模板，`cp` 成 config.yaml 后改。
- `requirements.txt`: 依赖清单(mlx-whisper / silero-vad / sounddevice / speechbrain / rumps …)。
- `install.sh`: venv 与依赖安装脚本。
- `README.md` / `claude_prompt.md`: 使用说明 / 给 Agent 的部署提示。
- `assets/`: 图标资源。`menubar.png`(品牌 logo 抠图→黑+alpha 模板图，菜单栏用) / `icon.png`(白色透明大图，App/Dock 用) / `logo_src.png`(原图留存，便于重生成)。
- `logs/`: 运行日志(out.log / err.log)，非源码。

## 数据流(单向，如河流)
```
mic → q(queue) → VADIterator 切句 → _accept(时长→能量→声纹) → _transcribe(whisper) → is_junk 过滤 → write_line
                                          │ 任一门不过 → _drop 计数，音频丢弃，永不进 whisper
```

法则: 成员完整·一行一文件·父级链接·三道门顺序=便宜的先拦(时长→能量→声纹模型最后跑)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
