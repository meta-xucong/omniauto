# 车源图片检索独立模块设计（2026-07-16）

## 0. 约束与目标

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)
- [dafengche_product_master_mirror_migration_design_20260713.md](dafengche_product_master_mirror_migration_design_20260713.md)

目标是把每台车的**每一张**大风车/手工图片建立可检索的视觉摘要；客户发图时，以临时图像指纹和现有识图文本为查询条件，找出高置信车源候选。它只提供受控证据，不能生成、替换或润色客户可见回复，回复仍只由 `customer_service_brain` 产出。

## 1. 边界与可移植性

```text
packages/vehicle_image_retrieval/                 可单独摘取的纯核心
  - V2 图片列表 -> 索引扩展写入
  - 索引状态/源指纹校验
  - 查询归纳词标准化与相似度排序
  - 不读取文件、不发 HTTP、不调用模型、不 import 应用

apps/.../optional_plugins/vehicle_image_retrieval/ 可选视觉描述实现
  - 图片字节 -> 指纹
  - 图片字节 -> 视觉模型归纳词
  - 独立配置、独立依赖、lazy load

apps/.../vehicle_image_retrieval_integration.py   本应用薄适配器
  - 读取本租户 V2 车源、受控加载官方/本地图片
  - 调用中性 optional-plugin 协议
  - 写回 V2 扩展、向现有视觉 bridge 增加证据
```

核心不得 import 微信、Brain、RPA、OCR、管理员 API、文件系统、Pillow 或任何具体视觉实现。识图插件与本模块互不 import；两者仅通过既有结构化图片理解结果和中性 optional-plugin 协议协作。模块缺失、模型失败、索引过期都必须降级为“不命中”，不得阻断文字客服，也不得改变其他插件生命周期。

## 2. V2 数据合同

大风车原始字段不变：

```text
source_payloads.vehicle_pictures.payload[]
```

只新增以下源中立扩展，绝不回写或改名原始 `pictureId`、`pictureNumber`、URL、描述等字段：

```json
{
  "extensions": {
    "vehicle_image_retrieval": {
      "schema_version": 1,
      "status": "ready",
      "source_payload_fingerprint": "sha256:...",
      "indexed_at": "...",
      "engine": {"name": "vehicle_image_retrieval", "version": "1"},
      "items": [
        {
          "picture_ref": "pictureId:img_...",
          "perceptual_hash": "...",
          "descriptor": {
            "summary": "白色奥迪 A4L 左前 45 度外观图",
            "keywords": ["奥迪", "A4L", "白色", "左前45度", "三厢轿车"],
            "identity_terms": ["奥迪", "A4L"],
            "view": "left_front",
            "scene_terms": ["室外", "展车"],
            "ocr_text": []
          }
        }
      ]
    }
  }
}
```

索引写入时保存图片源指纹。大风车下一次同步、手动新增/删除图片后，源指纹不一致即自动判为 `stale`，查询不能继续使用旧索引，直到重新索引成功。

## 3. 图片归纳与匹配策略

### 索引

管理员上传图片成功、或大风车同步成功且图片源发生变化后，宿主层把对应车源投入**独立、单工作者、按车源合并的后台队列**。先完成上传/同步的主落库，再异步索引；模型不可用、下载失败、入队异常均不能让主操作失败。短时间内同一车连续上传/同步会合并为一次或少量后续刷新，确保最终按最新图片源重建。管理员仍可通过内部接口立即手动重试单车索引。

适配器逐张取得图片字节，独立可选插件调用视觉模型，返回严格 JSON 的摘要、关键词、身份线索、拍摄角度、场景词和 OCR 文本；原始模型思维链、密钥、客户图片和图片二进制均不写入记录。每张商品图另计算 64 位感知指纹。失败会保留/显示为 `stale` 或 `failed`，客户侧只降级为不命中，绝不将旧图片索引当作当前车源证据。

### 客户查询

当前剪贴板交易已得到的客户图像只在内存中计算同一感知指纹，并复用既有识图输出生成查询归纳词，随后立即释放像素数据。核心对每个已就绪、未过期的图片索引比较：

1. 感知指纹相似度（同图、缩放、轻压缩、轻微截图的主要依据）；
2. 归纳词加权相似度（辅助排序与可审计解释）；
3. 以图片候选聚合为车源候选。

默认仅当感知相似度与综合分均超过阈值才会自动绑定某台车。仅凭“同品牌/同车型/同颜色”等文字线索最多作为推荐候选，不能把特定库存车写入会话上下文。这避免同款不同车误绑。

### Brain 接口

命中时适配器只补充：`matched`、`product_id`、`product_name`、`picture_ref`、综合分、各分量和审计原因。它将高置信 `product_id` 作为现有 `catalog_assist.preferred_candidate_ids` / 会话上下文的加性证据；Brain 仍通过本地 V2 商品库重新读取允许展示且未过期的字段。模块不直接调用大风车，也不写客户可见文字。

## 4. 内部接口

应用适配层提供稳定的内部 Python 接口：

- `index_product_vehicle_images(product_id, *, force=False)`：建立或刷新单车所有图片索引；
- `vehicle_image_retrieval_status(product_id)`：读取当前/过期/未配置状态；
- `match_customer_image_to_product_master(understanding, image_payload, config)`：对当前内存图片检索本地镜像；
- `merge_vehicle_image_match_into_catalog_assist(catalog_assist, image_match)`：只把高置信证据映射到既有桥接字段。
- `enqueue_vehicle_image_index(product_id, *, tenant_id, cause)`：宿主上传/同步成功后调用的非阻塞入队接口；不属于可移植核心。
- `vehicle_image_index_job_status(product_id, *, tenant_id)`：仅供管理台查看后台队列状态。

管理员 HTTP 接口只转发前两项：

- `GET /api/product-console/products/{product_id}/vehicle-image-retrieval`
- `POST /api/product-console/products/{product_id}/vehicle-image-retrieval/index`

索引失败返回结构化原因并保留旧索引为 `stale`，绝不假装图片已可匹配。

## 5. 验收与审计

必须覆盖：多图逐项入库、原始大风车载荷不变、手工图片与官方图片共存、索引过期拒绝命中、同图高置信命中、相同车型但不同图不自动绑定、插件缺失/模型失败的无害降级、客户图片字节不落盘、核心禁止依赖应用包，以及 Brain/RPA 外部合同回归。
