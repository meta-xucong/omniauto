# 1688 选择器与 URL 参数速查

## URL 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `keywords` | 搜索关键词，**必须 GBK 编码** | `%C2%D6%CC%A5` (轮胎) |
| `sortType` | 排序方式 | `price_sort-asc` 价格从低到高 |
| `beginPage` | 页码，从 1 开始 | `beginPage=1` |

完整示例：
```
https://s.1688.com/selloffer/offer_search.htm?keywords=%C2%D6%CC%A5&sortType=price_sort-asc&beginPage=1
```

## 列表页 DOM 选择器

```javascript
// 商品卡片
.search-offer-item, .offer-item

// 标题
.offer-title-row .title-text, .title a, a

// 价格
.offer-price-row .price-item, .text-main, .price

// 主图
.main-img img, img

// 链接
card.querySelector('a')

// 店铺名（若有）
.company-name, .shop-name, .offer-company
```

## 详情页 DOM 选择器

```javascript
// 店铺名
.company-name, .shop-name, [data-spm="seller"]

// 所在地
.location, .address, .region

// 经营模式
.business-model, .business-type

// 参数列表
.offer-attr-item, .props-item

// 详情图
.detail-content img, .description img
```

## 风控提示

- `sortType=price_sort-asc` 在部分类目下可能不生效，若发现页面未排序，回退到默认排序
- 详情页连续访问 10 个以上建议 `cooldown(5, 10)`
- 1688 详情页可能重定向到 login，开启 `auto_handle_login=True`
