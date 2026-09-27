# 制片曲库

将可商用且已核验授权的音乐文件放在本目录的子目录，并在 `catalog.json` 登记。不要提交未授权音乐。

每首曲目至少包含：`id`、`title`、`file`、`mood_tags`、`bpm` 和 `rights`。例如：

```json
{
  "id": "warm-farm-01",
  "title": "Warm Farm",
  "file": "licensed/warm-farm-01.mp3",
  "mood_tags": ["warm", "rural", "memory"],
  "bpm": 82,
  "rights": {"approved": true, "source": "license ledger", "scope": "commercial social"}
}
```

制片只会使用 `rights.approved=true`、文件完整的曲目；大文件先登记 `minimum_bytes`，如登记 `sha256` 会在选择前做完整性校验，避免未下载完的素材进入成片。选择结果会写入项目 `audio/bgm-selection.json`，并复制为项目内的 `audio/bgm.*` 后再参与最终混音。

音乐文件由 DGX/NAS 管理，默认不提交 Git；仓库只提交曲目台账、来源和授权范围。最终混音保留画面原有的环境声与动作声，BGM 作为可被旁白侧链压低的音乐床，而不是替换原声。
