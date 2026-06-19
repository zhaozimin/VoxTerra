#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 speechbrain.inference.speaker.EncoderClassifier(ECAPA-TDNN 声纹模型)、torch、numpy；
         读 config 的 speaker_threshold / speaker_profile / speaker_model
[OUTPUT]: 对外提供 SpeakerGate 类(enroll / verify / enrolled / available)
[POS]: voicelog 的「声纹门控」——夹在 Silero VAD 切句与 Whisper 转写之间，裁决「这句是不是机主本人」。
       与主文件的能量门(近场物理)互补：能量门挡远场视频外放，声纹门挡近场同语种他人/视频。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

设计哲学：fail-open。模型缺失 / 未注册 → 一律放行，绝不因声纹子系统故障而吞掉机主的话
         （丢一句=思想永久丢失，污染一行=肉眼可删，前者代价更高）。
"""
import os
import threading
from pathlib import Path

import numpy as np

SR = 16000


# ============================================================================
#  说话人嵌入：把任意一段语音映射成 192 维「音色指纹」(L2 归一化)，
#  同一人靠近、不同人远离，与说了什么无关(text-independent)。模型懒加载、线程安全。
# ============================================================================
class SpeakerGate:
    def __init__(self, profile_path: str, threshold: float = 0.40,
                 model_source: str = "speechbrain/spkrec-ecapa-voxceleb",
                 model_dir: str = "~/voicelog-models/ecapa"):
        self.profile_path = Path(os.path.expanduser(profile_path))
        self.threshold = float(threshold)
        self.model_source = model_source
        self.model_dir = os.path.expanduser(model_dir)
        self._clf = None                 # 懒加载的 ECAPA 分类器
        self._lock = threading.Lock()    # 模型加载/推理串行化，避免多线程重复加载
        self.ref = self._load_profile()  # 注册声纹质心(192,) 或 None
        self.last_err = ""

    # ---------------- 模型(懒加载，首次注册/校验时才付加载代价) ----------------
    def _model(self):
        if self._clf is None:
            from speechbrain.inference.speaker import EncoderClassifier  # 重导入，延后到真正需要
            self._clf = EncoderClassifier.from_hparams(
                source=self.model_source, savedir=self.model_dir,
                run_opts={"device": "cpu"},  # 单条短音频，CPU 足够且避开 MPS 算子坑
            )
        return self._clf

    def available(self) -> bool:
        """speechbrain/torch 是否就绪——不就绪则门控自动降级为放行。"""
        try:
            import speechbrain  # noqa: F401
            import torch        # noqa: F401
            return True
        except Exception:
            return False

    @property
    def enrolled(self) -> bool:
        return self.ref is not None

    # ---------------- 嵌入 ----------------
    def _embed(self, wav: np.ndarray) -> np.ndarray:
        """单段 float32 16k 单声道 → 192 维归一化嵌入。"""
        import torch
        with self._lock:
            x = torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32)).unsqueeze(0)
            e = self._model().encode_batch(x).squeeze().detach().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)

    # ---------------- 注册：多窗平均成质心，比单句更稳 ----------------
    def enroll(self, wav: np.ndarray, win_sec: float = 3.0) -> bool:
        """用一段较长录音(建议 20-30s)注册机主声纹：切成多个窗各取嵌入再平均、归一化、落盘。"""
        try:
            win = int(win_sec * SR)
            chunks = [wav[i:i + win] for i in range(0, max(1, len(wav) - win + 1), win)]
            chunks = [c for c in chunks if len(c) >= win // 2] or [wav]
            embs = np.stack([self._embed(c) for c in chunks])
            ref = embs.mean(axis=0)
            self.ref = ref / (np.linalg.norm(ref) + 1e-9)
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(self.profile_path, self.ref)
            self.last_err = ""
            return True
        except Exception as e:
            self.last_err = f"{type(e).__name__}: {e}"
            return False

    def _load_profile(self):
        try:
            return np.load(self.profile_path) if self.profile_path.exists() else None
        except Exception:
            return None

    # ---------------- 校验：是不是机主 ----------------
    def verify(self, wav: np.ndarray):
        """返回 (accept: bool, score: float)。
        未就绪 / 未注册 → fail-open 放行(True, 1.0)；否则按余弦相似度与阈值裁决。"""
        if not self.enrolled or not self.available():
            return True, 1.0
        try:
            score = float(self._embed(wav) @ self.ref)
            return score >= self.threshold, score
        except Exception as e:
            self.last_err = f"{type(e).__name__}: {e}"
            return True, 1.0  # 推理出错也放行，绝不因声纹故障吞掉机主的话
