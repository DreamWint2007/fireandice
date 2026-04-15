# 火与冰之舞 游戏指南



## 关卡文件格式规范

**自制关卡前请先阅读以下示例代码以了解格式！！！**

### 关卡代码示例:

```json
{
    "levelname": "examplelevel", 
    "initial_bpm": 123.4,
    "Beats": [
        {
            "angle": 90,
            "event": "none"
        },
        {
            "angle": 180,
            "event": "fast"
        },
        {
            "angle": 90,
            "event": "slow"
        },
        {
            "angle": 180,
            "event": "reverse"
        },
        {
            "angle": 270,
            "event": "none"
        },
        {
            "angle": 90,
            "event": "reverse"
        },
        {
            "angle": 180,
            "event": "complete"
        }
    ]
}
```

### 注意事项

levelname键值必须和关卡文件名和你在audio文件夹中放的音乐文件名一致(不含扩展名)，且不得和已有的关卡重复


initial_bpm为关卡初始预设bpm，对应