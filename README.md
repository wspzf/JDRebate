# 京东返利插件 (JDRebate)

## 概述

京东返利插件是一款为基于 `xxxbot` 的微信机器人设计的插件。它可以自动识别微信聊天（包括群聊和私聊）中用户发送的京东商品链接或京东商品卡片分享，并将其转换为带有推广返利的链接。转换后的链接会以更美观、信息更丰富的格式发送回给用户。

## 主要功能

- **自动识别京东链接**: 能够识别文本消息中符合特定模式的京东商品链接。
- **处理京东商品卡片**: 能够解析XML格式的微信消息，提取从小程序或App分享的京东商品信息（如SKU），并构建标准商品链接进行转链。
- **链接转换**: 调用第三方API（折京客）将原始京东链接转换为推广链接。
- **返利信息展示**: 可配置是否在转链后的消息中展示预计的返利金额。
- **灵活的适用范围控制**:
    - 支持三种群组/用户控制模式：
        - `all`: 插件对所有群聊和私聊生效。
        - `whitelist`: 插件仅对在 `group_list` 中列出的群聊ID或用户ID生效。
        - `blacklist`: 插件对所有群聊和私聊生效，但在 `group_list` 中列出的群聊ID或用户ID除外。
- **多种链接处理**:
    - 单个链接：直接发送包含商品标题、价格、优惠券和返利信息的卡片式消息。
    - 多个链接：替换原始消息中的每个京东链接为其对应的短推广链接。

## 文件结构

```
JDRebate/
├── main.py         # 插件主逻辑实现
├── config.toml     # 插件配置文件
└── readme.md       # 本说明文件
```

## 配置说明 (`config.toml`)

配置文件位于插件目录下的 `config.toml`。

```toml
[basic]
# 是否启用插件 (true: 启用, false: 禁用)
enable = true

# 折京客API相关配置 (请替换为您的真实信息)
appkey = "您的折京客appkey"
union_id = "您的京东联盟ID"

# 群组控制模式:
# "all": 允许所有群聊和私聊。
# "whitelist": 仅允许 group_list 中的群聊/用户。
# "blacklist": 允许所有群聊和私聊，但排除 group_list 中的群聊/用户。
group_mode = "all"

# 群组/用户列表 (配合 whitelist 或 blacklist 模式使用)
# 当 group_mode 为 "whitelist" 时，这里是白名单。
# 当 group_mode 为 "blacklist" 时，这里是黑名单。
# 示例:
# group_list = [
#     "群聊ID1@chatroom",
#     "用户微信ID1",
#     "群聊ID2@chatroom",
# ]
group_list = []

# (已废弃，正则表达式硬编码在 main.py 中)
# jd_link_pattern = "https?:\\/\\/[^\\s<>]*(?:3\\.cn|jd\\.|jingxi|u\\.jd\\.com)[^\\s<>]+"

# (已废弃，API URL 硬编码在 main.py 中)
# api_url = "http://api.zhetaoke.com:20000/api/open_jing_union_open_promotion_byunionid_get.ashx"

# API附加参数 (通常无需修改)
signurl = "5"      # "5" 返回更详细的商品信息
chain_type = "2"   # "2" 返回短链接

# 是否显示返利金额 (true: 显示, false: 不显示)
show_commission = true
```

### 配置项详解:

-   `enable`: 布尔值。`true` 表示启用插件，`false` 表示禁用。
-   `appkey`: 字符串。您在折京客平台申请的 `appkey`。
-   `union_id`: 字符串。您的京东联盟ID。
-   `group_mode`: 字符串。控制插件的适用范围。
    -   `"all"`: 对所有来源的消息都尝试进行转链。
    -   `"whitelist"`: 仅处理来自 `group_list` 中指定群聊或用户的消息。
    -   `"blacklist"`: 处理所有来源的消息，但会忽略 `group_list` 中指定的群聊或用户。
-   `group_list`: 列表。包含群聊ID (通常以 `@chatroom` 结尾) 或用户微信ID的字符串列表。
-   `signurl`: 字符串。折京客API参数，影响返回数据的详细程度，默认为 `"5"`。
-   `chain_type`: 字符串。折京客API参数，控制返回链接的类型，默认为 `"2"` (短链接)。
-   `show_commission`: 布尔值。`true` 会在转链消息中显示预计返利金额，`false` 则不显示。

## 使用方法

1.  **获取并配置**:
    *   将 `JDRebate` 文件夹放置到您的机器人插件目录下。
    *   根据上述说明修改 `config.toml` 文件，填入您的 `appkey` 和 `union_id`，并根据需求设置 `group_mode` 和 `group_list` 等。
2.  **启用插件**:
    *   确保 `config.toml` 中的 `enable` 设置为 `true`。
    *   重启或重载您的微信机器人以加载插件。
3.  **使用**:
    *   当在允许的聊天中（根据 `group_mode` 和 `group_list` 配置）发送包含京东商品链接的文本消息时，插件会自动回复转换后的推广链接和商品信息。
    *   当在允许的聊天中分享京东商品卡片（例如，从京东App或京东小程序分享）时，插件也会自动处理并回复。

## 内部逻辑简述 (`main.py` - v1.2.0)

-   **初始化 (`__init__`)**:
    -   加载 `config.toml` 配置。
    -   设置 `api_url` (硬编码为折京客的特定接口)。
    -   编译京东链接的正则表达式。
-   **消息处理**:
    -   `handle_text`: 监听文本消息。如果插件启用且消息来源符合配置，则查找消息内容中的京东链接。
    -   `handle_xml`: 监听XML消息（通常是应用分享卡片）。如果插件启用且消息来源符合配置，则尝试解析XML，提取京东商品信息（URL、SKU，或从小程序pagepath中解析URL）。
-   **API响应解析 (`_parse_api_response`)** (v1.2.0新增):
    -   核心方法，用于解析来自折京客API的JSON响应。
    -   能够识别和处理API可能返回的两种主要数据结构（一种嵌套较深主要含链接，一种扁平含完整商品信息）。
    -   提取关键数据如 `shorturl`, `clickURL`, `title`, `price` 等。
-   **来源检查 (`_check_allowed_source`)**: 根据 `group_mode` 和 `group_list` 判断消息发送者（群或个人）是否有权使用此插件。
-   **链接处理 (`_process_links_in_text`)**:
    -   从文本中提取所有京东链接。
    -   如果只有一个链接，调用 `convert_link` 生成包含详细信息的回复 (或简化回复，如果API返回信息不足)。
    -   如果有多个链接，调用 `convert_link_official` 对每个链接生成短链接，并替换原文中的链接后发送。
-   **链接转换**:
    -   `convert_link` (v1.2.0调整): 调用折京客API，通过 `_parse_api_response` 解析后，获取商品信息。如果信息完整，格式化为用户友好的消息文本；如果信息精简（如仅有链接），则发送简化版回复。
    -   `convert_link_official` (v1.2.0调整): 调用折京客API，通过 `_parse_api_response` 解析后，按优先级获取最合适的推广链接 (`shorturl` > `clickURL` > `coupon_click_url` > `item_url`)。
-   **URL清理和识别**:
    -   `_is_jd_link`: 使用正则表达式判断一个URL是否为京东链接。
    -   `_clean_url`: 清理URL，去除不必要的查询参数。

## 注意事项

-   **API依赖**: 本插件依赖折京客API进行链接转换。请确保您的 `appkey` 和 `union_id` 正确，并且API服务可用。
-   **配置更新**: 修改 `config.toml` 后，通常需要重启机器人或重载插件才能使新配置生效。
-   **日志**: 插件会通过 `loguru` 记录详细的操作日志，方便排查问题。日志级别和输出位置取决于您主程序的 `loguru` 配置。

## 总结与反思

-   **已完成 (截至v1.2.0)**:
    -   `api_url` 已硬编码到脚本中，简化了配置。
    -   `allowed_groups` 逻辑已重构为更灵活的 `group_mode` (all, whitelist, blacklist) 和 `group_list`，支持私聊。
    -   能够处理文本消息中的单个或多个京东链接。
    -   能够处理XML分享卡片中的京东商品信息，并增强了从小程序路径提取链接的逻辑。
    -   **显著增强了对折京客API不同响应格式的兼容性**，能够正确处理商品长链和各类短链（如 `u.jd.com`）。
-   **潜在改进点**:
    -   **错误处理与用户反馈**: 当前API请求失败或返回无效数据时，虽然日志更详细了，但仍可考虑在转换失败时给用户更明确的聊天内提示。
    -   **API密钥安全性**: `appkey` 直接写在配置文件中，对于分发插件的场景，仍建议考虑更安全的管理方式。
    -   **可扩展性**: 如果未来需要支持更多转链平台，API调用部分仍需进一步抽象。
    -   **自定义回复格式**: 用户可能希望自定义回复消息的格式。
    -   **京东短链服务不稳定性**: 某些京东短链解析可能仍存在不确定性，可探索更鲁棒的原始链接还原方法。
    -   **SKU提取的健壮性**: 京东小程序分享格式若再次变更，相关提取逻辑可能仍需调整。

---

## 更新日志

### v1.2.0 (2025-05-11)

- 新增：返利群组控制
- 优化：解决非商品URL不能转链的问题

### v1.1.0

- 新增：支持京东小程序分享链接的识别与转链
- 新增：配置选项控制是否显示返利金额
- 优化：简化了输出内容格式，提高可读性
- 优化：提升XML消息处理能力，支持更多类型的分享
- 修复：修正了部分链接无法正确识别的问题

### v1.0.0

- 初始版本发布
- 支持基本的京东链接识别和转链功能
- 支持群组限制功能

---

希望这份文档能帮助您更好地理解和使用京东返利插件！ 