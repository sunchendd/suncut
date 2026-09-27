# 配音演员库

`catalog.json` 是可被配音演员 agent 选择的音色资产清单。预置声线可立即使用；真人样本、克隆模型或自训练声音必须另建条目，并附带 `consent_reference`、使用范围与来源。

推荐本地引擎为 CosyVoice：以独立容器/环境部署，避免污染短剧生成环境。项目侧只通过 `engine=cosyvoice` 和已授权的音色 ID 调用；没有完整授权的真人样本不会进入可选池。

## 演员音色入库流程

1. 演员签署授权，保存授权文件或工单号；不要把身份证、手机号等个人信息写入目录。
2. 录制 20–60 秒、安静无配乐的中文参考音频，存到仅限项目管理员访问的 `voice_library/private/` 或 NAS 私有目录。
3. 在独立 CosyVoice 环境对参考音频试听；试听通过后才把下列条目加入 `catalog.json`，并把 `rights.approved` 设为 `true`。
4. 项目的 `audio/voice-profiles.json` 用角色名指定该 `voice` ID。配音 agent 会把实际分配、授权引用和表演提示写入 `dubbing.json`，以便复配和审计。

示例（占位符不可直接启用）：

```json
{
  "id": "cosy-actor-li-01",
  "label": "李演员-青年男声",
  "engine": "cosyvoice",
  "reference_audio": "private/cosy-actor-li-01.wav",
  "languages": ["zh-CN"],
  "tags": ["male", "young", "natural"],
  "rights": {"approved": true, "consent_reference": "consent/2026-001", "scope": "本工坊短剧"}
}
```

目前线上工作流已经可为每个角色选择不同的 Edge 预置声线，并强制按底层声线去重。CosyVoice 克隆音色的目录校验和授权门禁已经具备；安装其独立推理服务并接入后，才会允许该 `engine` 参与合成，避免在模型或授权不完整时把真人声线误用到成片。
