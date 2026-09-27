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

制片只会使用 `rights.approved=true` 且文件存在的曲目；选择结果会写入项目 `audio/bgm-selection.json`，并复制为项目内的 `audio/bgm.*` 后再参与最终混音。
