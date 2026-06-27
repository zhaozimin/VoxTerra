# voicelog/
> L2 | 父级: ../CLAUDE.md

应用本体：一个常驻进程把贴身麦的语音实时切句、过门控、本地转写、写进当天 Markdown。音频绝不落盘。
**一套引擎 · 两层外壳**：同一个 `VoiceLogApp`/`Recorder`/心跳，由 `app_flavor`(或 env `VOICELOG_FLAVOR`) 选形态——
`lite`(默认)= 只在菜单栏，无 Dock；`full` = 常驻 Dock + 主窗口(首页/历史/设置/关于) 与菜单栏并存。

## 成员清单
- `voicelog_menubar.py`: 主程序与唯一进程。采集(sounddevice) → 切句(silero VADIterator) → **转写前三道门**(时长/能量近场/声纹) → 转写(mlx-whisper large-v3) → 复读+水印过滤 → 专名纠错(`apply_replace`:ASCII 键空白/连字符弹性匹配吸收 whisper「web coding/webcoding/Web-coding」多形态,键全小写则大小写不敏感、含大写则区分守 Cloud≠cloud,词边界防 iCloud 误伤;同构副本在 `voicelog_win.py`) → 按时区写当天笔记(外置盘掉线回退内置)。rumps 菜单栏：计数/滤除数、暂停、注册声音、声纹门开关、时区、保存位置、打开笔记、参数设置。**形态总开关 `FULL_APP`**：full 时 `floor_regular()` 常驻 Dock 并构建 `main_window.MainWindow`，每拍心跳刷新它。**Phase2/3 文件桥接**(供 SwiftUI 全窗口前端 `../mac/`)：tick 末尾 `_process_commands()`(消费 BRIDGE/commands.json)+`_write_state()`(写 BRIDGE/state.json,BRIDGE=~/Library/Application Support/VoiceLog,固定);桥接命令复用现成函数(toggle/enroll/set_config_*/set_vault/四档 download_model_by_id·model_cancel·use_model_by_id·delete_model_by_id;下载用代际守护防取消后重点踩状态,state 暴露 model_result/result_id 供前端显失败反馈)。**`HeadlessApp`**：env `VOICELOG_HEADLESS=1` 时走它——无 rumps/菜单栏,只跑 Recorder + 2s 循环写状态/读命令,供 SwiftUI App 作 sidecar 拉起(单图标完整 App)。**`run()` 启动即持有 `_begin_no_app_nap()` 的 `NSProcessInfo.beginActivity` 令牌至进程退出 → 退出 App Nap**(常驻引擎 4G footprint 闲置会被节流+换出 3.7G,致唤醒首拍卡顿;`AllowingIdleSystemSleep` 仅退 Nap、仍允许整机休眠)。菜单栏路径零改动。
- `main_window.py`: **全窗口产品外壳(V1·full 形态)**。Dock 主窗口 = 侧边栏 + 四页：首页(状态/大开关/统计/今日实时流) · 历史(日期列+内容+跨日搜索) · 设置(复用 settings_ui 卡片工厂的滚动参数卡 + 保存位置 + 入口按钮) · 关于(介绍/版本/检查更新/作者链接)。**纯编排层**：经 `sys.modules[type(app).__module__]` 取活引擎、转调 app 现成回调，绝不复制业务。导入即用 `objc.Category` 给 rumps delegate 补「点 Dock 图标重开窗」。
- `settings_ui.py`: **参数设置 UI 面**。门控阈值做成卡片式 滑块+可编辑数字框+范围+越小/越大说明。`make_param_card` 是**卡片单一真相源**——模态设置窗(`SettingsWindow.run_modal`)与全窗口设置页(main_window)共用它；`read_card_values` 统一读卡；`_quantize`/`_fmt` 纯函数可单测。
- `voicelog_win.py`: **Windows/跨平台托盘版入口**(与 macOS 的 voicelog_menubar.py 对等)。同构管线
  (采集→VAD→三道门→转写→过滤→写盘)+ 掉线自愈;转写注入 `transcribe_fw`,托盘用 pystray,无弹窗 UI
  (设置改 config.yaml,声纹注册走托盘+系统通知)。数据落 `%APPDATA%\VoiceLog`。复用 speaker/i18n。
- `transcribe_fw.py`: faster-whisper(CTranslate2) 转写封装,接口与 mlx_whisper.transcribe 对齐(吃 16k
  float32,吐文本)。有 N 卡 cuda/float16,否则 cpu/int8。Windows 端的转写引擎,亦可在 Mac 验证。
- `model_fetch.py`: 跨平台「模型获取」中枢(mac/win 共用)。**绕开 HF/镜像,直接从本项目 GitHub Release
  下载模型 zip**(国内可达)。`download_model` = **自带重试的断点续传器**(为慢/频繁中断的网络而生,点一次磨到下满):
  断后从 .part 精确字节带 Range 续(权威 total 取 Content-Range,认 206 分片);有进展清失速、每次断后至少歇 _MIN_NAP
  杜绝热循环;连续 _MAX_STALLS 零进展或累计下载超 _ABS_CAP(4G)即放弃,绝不挂死;.part 放 dest 同盘(不被系统清、
  落地不跨盘);should_cancel 可中途停(留 part 续),status dict 回填 ok/cancelled/fail。`model_ready` 判本地就绪。
  config 模型项写 `auto` 即托管模式(放 …/VoiceLog/models)。是「三层模型兜底」第一层。`model_status_key()`
  把「下载中/已就绪/托管缺失/直连缺失」四态收敛成纯函数(mac/win 共用,可单测),驱动菜单常显的模型状态行。
- `update_check.py`: 跨平台「查更新」中枢。启动后台查 GitHub Releases 最新正式版,`is_newer` 纯函数比版本号。mac/win 共用。
- `auto_update.py`: 「真·自动更新」执行层。点更新→下载新包→**三关校验**(codesign 签名完整 + spctl 公证放行 +
  TeamID 是本人,挡篡改)→ mac 派 helper 等本进程退出后 `ditto` 原子替换+重启(失败回滚不致砖);win 跑新 Setup.exe
  由 Inno 覆盖。`asset_url`/`app_bundle_root` 纯函数可单测。源码运行识别为非打包→退回打开下载页。
- `speaker.py`: 声纹门控子模块。`SpeakerGate` 用 ECAPA-TDNN(speechbrain) 把语音映射成 192 维音色指纹，注册机主质心后逐句算余弦相似度裁决「是不是机主」。懒加载、fail-open(未注册/故障一律放行)、附「提取质量」自一致性指标。
- `enroll_ui.py`: 声纹注册 UI 面(PyObjC/Cocoa)。`EnrollWindow` 两阶段：须知页(本地/隐私说明+开始按钮，不录音)→点开始→朗读页(句子+进度条)。纯展示层，采集逻辑在主文件 `Recorder.enroll`(质量驱动)，进度由 rumps.Timer 喂。
- `replace_ui.py`: 关键词管理 UI 面(PyObjC/Cocoa，**模态**——无 Dock 进程唯有模态窗口能稳拿键盘焦点)。`ReplaceWindow.run_modal()` 返回编辑后的文本，主文件 `parse_corrections`/`write_corrections` 解析为「精确纠错 rules(`错=正`) + 识别词库 terms(单写目标词，注入 prompt)」并写回 config。
- `i18n.py`: 多语言中枢(中/英/日)。**界面语言**(UI 文案+注册文案,config `ui_language`) 与 **主语言**(=whisper 转写语言,config `primary_language`) **解耦**；**辅语言**(`secondary_language`)注入 initial_prompt 强化中英混说偏置。菜单栏三子菜单独立切换。
- `ui_common.py`: 各原生窗口公共底座。`KeyWindow`(模态窗基类：LSUIElement 无主菜单致标准编辑快捷键失效，在窗口层拦截 Cmd+C/V/X/A/Z 转发焦点文本框) + `BtnTarget`(按钮回调桥) + `make_label`/`make_rich_label`(标签) + `push_regular`/`pop_regular`(激活策略引用计数：开窗变前台、计数归零回无 Dock) + `floor_regular`(full 形态把 Regular 钉死垫底，模态子窗 push/pop 永不切回无 Dock)，被 enroll_ui / replace_ui / settings_ui / main_window 共用。
- `config.yaml`: 运行配置(本机实际值)。模型路径、设备、时区、术语偏置、纠错表、**三道门阈值**、回退目录。
- `config.example.yaml`: 配置模板，`cp` 成 config.yaml 后改。
- `requirements.txt`: 依赖清单(mlx-whisper / silero-vad / sounddevice / speechbrain / rumps …)。
- `install.sh`: venv 与依赖安装脚本。
- `README.md` / `claude_prompt.md`: 使用说明 / 给 Agent 的部署提示。
- `assets/`: 图标资源。`logo_src.png`(3D 写实彩色母版:麦克风+无限符号+绛红线,自带深色背景,**App/Dock/Finder/README 图标真相源**,make_icon/make_ico 由它裁满铺圆角) / `menubar.png`(品牌 logo 抠图→黑+alpha 模板图,**菜单栏状态栏用,保持原样**,isTemplate 自动反色) / `icon.png`(白色透明 logo,现仅供 Windows `_tray_image` 合成到深色圆角底;App/Dock 图标已改由 logo_src.png 出)。
- `logs/`: 运行日志(out.log / err.log)，非源码。

## 数据流(单向，如河流)
```
mic → q(queue) → VADIterator 切句 → _accept(时长→能量→声纹) → _transcribe(whisper) → is_junk 过滤 → write_line
                                          │ 任一门不过 → _drop 计数，音频丢弃，永不进 whisper
```

法则: 成员完整·一行一文件·父级链接·三道门顺序=便宜的先拦(时长→能量→声纹模型最后跑)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
