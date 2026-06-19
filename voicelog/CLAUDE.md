# voicelog/
> L2 | 父级: ../CLAUDE.md

应用本体：一个常驻菜单栏进程，把贴身麦的语音实时切句、过门控、本地转写、写进当天 Markdown。音频绝不落盘。

## 成员清单
- `voicelog_menubar.py`: 主程序与唯一进程。采集(sounddevice) → 切句(silero VADIterator) → **转写前三道门**(时长/能量近场/声纹) → 转写(mlx-whisper large-v3) → 复读+水印过滤 → 专名纠错 → 按时区写当天笔记(外置盘掉线回退内置)。rumps 菜单栏：计数/滤除数、暂停、注册声音、声纹门开关、时区、保存位置、打开笔记。
- `speaker.py`: 声纹门控子模块。`SpeakerGate` 用 ECAPA-TDNN(speechbrain) 把语音映射成 192 维音色指纹，注册机主质心后逐句算余弦相似度裁决「是不是机主」。懒加载、fail-open(未注册/故障一律放行)、附「提取质量」自一致性指标。
- `enroll_ui.py`: 声纹注册 UI 面(PyObjC/Cocoa)。`EnrollWindow` 自建原生窗口：统一排版的朗读稿 + 实时进度条 + 状态/质量反馈 + 取消。纯展示层，只读 state 渲染，采集逻辑在主文件 `Recorder.enroll`(质量驱动)。
- `replace_ui.py`: 关键词管理 UI 面(PyObjC/Cocoa，**模态**——无 Dock 进程唯有模态窗口能稳拿键盘焦点)。`ReplaceWindow.run_modal()` 返回编辑后的文本，主文件 `parse_corrections`/`write_corrections` 解析为「精确纠错 rules(`错=正`) + 识别词库 terms(单写目标词，注入 prompt)」并写回 config。
- `ui_common.py`: 各原生窗口公共底座。`BtnTarget`(按钮回调桥) + `make_label`(只读标签)，被 enroll_ui / replace_ui 共用。
- `config.yaml`: 运行配置(本机实际值)。模型路径、设备、时区、术语偏置、纠错表、**三道门阈值**、回退目录。
- `config.example.yaml`: 配置模板，`cp` 成 config.yaml 后改。
- `requirements.txt`: 依赖清单(mlx-whisper / silero-vad / sounddevice / speechbrain / rumps …)。
- `install.sh`: venv 与依赖安装脚本。
- `README.md` / `claude_prompt.md`: 使用说明 / 给 Agent 的部署提示。
- `logs/`: 运行日志(out.log / err.log)，非源码。

## 数据流(单向，如河流)
```
mic → q(queue) → VADIterator 切句 → _accept(时长→能量→声纹) → _transcribe(whisper) → is_junk 过滤 → write_line
                                          │ 任一门不过 → _drop 计数，音频丢弃，永不进 whisper
```

法则: 成员完整·一行一文件·父级链接·三道门顺序=便宜的先拦(时长→能量→声纹模型最后跑)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
