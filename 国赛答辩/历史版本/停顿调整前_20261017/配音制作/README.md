# AI 女声配音交付

- [最终视频](B09018834_AI配音版.mp4)：166.500 秒，1920×1080、24 fps，普通话女声，无新增字幕。
- [完整配音 MP3](AI女声_完整配音.mp3) / [WAV](AI女声_完整配音.wav)：包含与画面对齐的停顿，可直接从 0 秒同步播放。
- [配音时间线](配音时间线.json) / [实测核对](音画核对.json)：19 段正文、计划窗口与实际进出点。
- [无声底片](B09018834_无声底片.mp4)：已移除旧音轨，保留原录屏画面。

使用 [Kokoro v1.1 中文模型](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html)，中文女声 `zf_001`（speaker ID 3），通过 sherpa-onnx 1.13.8 在本机离线合成。模型下载后不发送讲稿、视频或音频到在线语音服务。

按实际动作分段放置音频，用静音保留观察时间。箱体位移在推障后说明，标记误差在室内观察后说明，返航位置误差仅在终端显示 complete 后说明。单段语音按合成语速适配窗口，没有裁切台词、重复音轨或生成字幕。

最终使用 ffmpeg 显式映射原视频画面和新语音音轨，视频 `-c:v copy`。画面流哈希与原片一致，3996 帧完整保留；成片只有一条新 AAC 音轨、零字幕轨。音量统一至约 -17 LUFS。

同步更新 `国赛答辩/B09018834.mp4`、`avs_ws/submission/B09018834.mp4` 和答辩 PPT 第 3 页内嵌视频。原有人声版本保存在 `国赛答辩/历史版本/AI配音替换前_20261017_080255/`。

## 重建

运行依赖：Python、numpy、sherpa-onnx、ffmpeg。临时依赖安装于 `/tmp/avs_tts_deps`，模型在 `/tmp/kokoro-int8-multi-lang-v1_1`；临时目录被清理后需重新安装并下载模型，已交付的音视频不依赖这些临时文件。

```bash
PYTHONPATH=/tmp/avs_tts_deps python3 国赛答辩/配音制作/build_ai_voiceover.py --model-dir /tmp/kokoro-int8-multi-lang-v1_1
```

重建脚本只生成本目录的候选成片及核对文件；发布至答辩/提交视频、重建 PPT 需随后同步。
