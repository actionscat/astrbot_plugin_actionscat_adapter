# astrbot_plugin_actionscat_adapter

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](LICENCE)
[![AstrBot Plugin](https://img.shields.io/badge/AstrBot-Plugin-blueviolet.svg)](https://astrbot.dev/)

AstrBot-side ActionsCat adapter.

## Contract

Example:
```json
{
  "sender_qq": "114514",
  "current_group": "dm",
  "raw_msg": "小米自研玄戒O1芯片深度评测：直逼8 Elite！ https://www.bilibili.com/video/BV18sJHz5ENR/?spm_id_from=333.1387.favlist.content.click&vd_source=9a0e2be66beaff71d0754773d78aa6fb"
}
```

Note:

- `sender_qq`: Sender's QQ number.
- `current_group`: Current group number; for private chat, it is `dm`.
- `raw_msg`: The original text provided by AstrBot.

## Environmental variable

The `.env` file in the plugin directory is read by default.

Default：

```text
POST http://127.0.0.1:8080/v1/dispatch
```

## Backend Response 
WIP

```json
{
  "messages": [
    {"type": "text", "text": "hello"},
    {"type": "image_url", "url": "https://example.com/a.png"}
  ]
}
```

If the backend returns the following result, the adapter will not reply to the group chat.

```json
{"code": "NO_MATCH"}
```
