"""Official Dafengche Open Platform contract fragments used by the mirror.

The tuples in this module are intentionally boring: they are the local audit
anchor for the fields documented in ``大风车开放平台标准接口文档``.  Runtime
code must preserve upstream payloads verbatim and may only build projections
from these paths; it must not invent a competing vehicle schema.
"""

from __future__ import annotations

from dataclasses import dataclass


SHOP_API = "com.souche.danube.portal.dubbo.open.api.ShopOpenService#getByCode"
CAR_IDS_API = "com.souche.danube.portal.dubbo.open.api.CarOpenService#listCarIdsByShopCodeAndOperationPhase"
CAR_DETAIL_API = "com.souche.danube.portal.dubbo.open.api.CarOpenService#getById"
CAR_PICTURES_API = "com.souche.danube.portal.dubbo.open.api.CarPictureOpenService#findByCarId"
CAR_UPDATE_API = "com.souche.danube.portal.dubbo.open.api.CarOpenService#update"


@dataclass(frozen=True)
class FieldSpec:
    path: str
    label: str
    customer_visible_by_default: bool = False
    restricted_by_default: bool = False


SHOP_FIELD_SPECS = (
    FieldSpec("id", "店铺ID"),
    FieldSpec("orgId", "集团ID"),
    FieldSpec("departmentId", "departmentId"),
    FieldSpec("parentDepartmentId", "组织结构ID"),
    FieldSpec("name", "门店名称"),
    FieldSpec("code", "门店code"),
    FieldSpec("internalAbbreviation", "对内简称"),
    FieldSpec("externalAbbreviation", "对外简称"),
    FieldSpec("mobile", "联系人手机", restricted_by_default=True),
    FieldSpec("contactName", "联系人姓名", restricted_by_default=True),
    FieldSpec("telephone", "座机号码", restricted_by_default=True),
    FieldSpec("provinceCode", "省份code"),
    FieldSpec("cityCode", "城市code"),
    FieldSpec("regionCode", "区域code"),
    FieldSpec("address", "详细地址"),
    FieldSpec("creator", "创建人ID", restricted_by_default=True),
    FieldSpec("operator", "修改人ID", restricted_by_default=True),
    FieldSpec("picture", "图片"),
    FieldSpec("logo", "门店logo"),
    FieldSpec("video", "视频"),
    FieldSpec("whetherTest", "是否测试店"),
)

VEHICLE_DETAIL_FIELD_GROUP_SPECS = (
    (
        "vehicle_identity",
        "车源识别",
        (
            FieldSpec("carId", "大风车车源 ID"),
            FieldSpec("orgId", "集团 ID", restricted_by_default=True),
            FieldSpec("shopCode", "大风车店铺编码"),
            FieldSpec("owner", "记录负责人 ID", restricted_by_default=True),
            FieldSpec("creator", "创建人 ID", restricted_by_default=True),
            FieldSpec("operationPhase", "业务阶段", customer_visible_by_default=True),
        ),
    ),
    (
        "base_car_info",
        "基础车辆信息",
        (
            FieldSpec("baseCarInfo.vinNumber", "VIN 码", restricted_by_default=True),
            FieldSpec("baseCarInfo.name", "品牌车系对象", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.name.brandCode", "品牌 code"),
            FieldSpec("baseCarInfo.name.brandName", "品牌", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.name.seriesCode", "车系 code"),
            FieldSpec("baseCarInfo.name.seriesName", "车系", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.name.modelCode", "车型 code"),
            FieldSpec("baseCarInfo.name.modelName", "车型", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.name.displayValue", "车辆展示名称", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.firstLicensePlateDate", "首次上牌时间", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.area", "车辆所在地"),
            FieldSpec("baseCarInfo.area.cityCode", "车辆所在地城市 code"),
            FieldSpec("baseCarInfo.area.cityName", "车辆所在地城市名"),
            FieldSpec("baseCarInfo.area.provinceCode", "车辆所在地省份 code"),
            FieldSpec("baseCarInfo.area.provinceName", "车辆所在地省份名"),
            FieldSpec("baseCarInfo.area.displayValue", "车辆所在地展示值", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.registerArea", "车辆归属地"),
            FieldSpec("baseCarInfo.registerArea.cityCode", "车辆归属地城市 code"),
            FieldSpec("baseCarInfo.registerArea.cityName", "车辆归属地城市名"),
            FieldSpec("baseCarInfo.registerArea.provinceCode", "车辆归属地省份 code"),
            FieldSpec("baseCarInfo.registerArea.provinceName", "车辆归属地省份名"),
            FieldSpec("baseCarInfo.registerArea.displayValue", "车辆归属地展示值"),
            FieldSpec("baseCarInfo.stockStatus", "库存状态", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.contractSignDate", "采购日期", restricted_by_default=True),
            FieldSpec("baseCarInfo.vehicleCondition", "车况（对内）"),
            FieldSpec("baseCarInfo.carDetailForDisplay", "车辆描述（对外）", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.color", "车身颜色", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.innerColor", "内饰颜色", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.productionDate", "出厂日期", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.annualExpiresDate", "年检到期日"),
            FieldSpec("baseCarInfo.outStockDate", "退库日期"),
            FieldSpec("baseCarInfo.inStock", "入库日期"),
            FieldSpec("baseCarInfo.reserveTime", "预定日期"),
            FieldSpec("baseCarInfo.payTime", "销售日期"),
            FieldSpec("baseCarInfo.mileage", "表显里程（公里）", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.outStockReason", "退库原因"),
            FieldSpec("baseCarInfo.outStockReasonRemarks", "退库原因备注"),
            FieldSpec("baseCarInfo.salesperson", "销售员", restricted_by_default=True),
            FieldSpec("baseCarInfo.useType", "使用性质", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.plateNumber", "车牌号", restricted_by_default=True),
            FieldSpec("baseCarInfo.carRemark", "备注", restricted_by_default=True),
            FieldSpec("baseCarInfo.vehicleNumber", "车辆编号"),
            FieldSpec("baseCarInfo.purchaseType", "采购类型"),
            FieldSpec("baseCarInfo.assessmentPhotoList", "评估采购资料照片"),
            FieldSpec("baseCarInfo.video", "车辆视频", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.weidianIsUpshelf", "微店上架状态", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.upShelfDate", "微店上架时间", customer_visible_by_default=True),
            FieldSpec("baseCarInfo.downShelfDate", "微店下架时间"),
            FieldSpec("baseCarInfo.detectReportPdf", "检测报告"),
            FieldSpec("baseCarInfo.detectReportPdf.url", "检测报告地址"),
            FieldSpec("baseCarInfo.detectReportPdf.name", "检测报告名称"),
        ),
    ),
    (
        "owner_information",
        "车主信息",
        (
            FieldSpec("carOwnerInfo", "车主信息", restricted_by_default=True),
            FieldSpec("carOwnerInfo.payee", "收款人", restricted_by_default=True),
            FieldSpec("carOwnerInfo.address", "地址（车主信息）", restricted_by_default=True),
            FieldSpec("carOwnerInfo.bankId", "银行卡号", restricted_by_default=True),
            FieldSpec("carOwnerInfo.identify", "身份证号", restricted_by_default=True),
            FieldSpec("carOwnerInfo.phoneNumber", "手机号码", restricted_by_default=True),
            FieldSpec("carOwnerInfo.purchaseTax", "购置税", restricted_by_default=True),
            FieldSpec("carOwnerInfo.customerName", "车主姓名", restricted_by_default=True),
            FieldSpec("carOwnerInfo.customerType", "客户类型", restricted_by_default=True),
            FieldSpec("carOwnerInfo.otherAccount", "其他账户", restricted_by_default=True),
            FieldSpec("carOwnerInfo.purchaseSource", "采购来源", restricted_by_default=True),
            FieldSpec("carOwnerInfo.openAccountBank", "开户行", restricted_by_default=True),
        ),
    ),
    (
        "price_information",
        "价格信息",
        (
            FieldSpec("carPriceInfo.purchasePrice", "采购价", restricted_by_default=True),
            FieldSpec("carPriceInfo.newPrice", "新车指导价"),
            FieldSpec("carPriceInfo.dealPrice", "成交价", restricted_by_default=True),
            FieldSpec("carPriceInfo.exhibitionPrice", "展厅标价"),
            FieldSpec("carPriceInfo.salesPrice", "销售底价", restricted_by_default=True),
            FieldSpec("carPriceInfo.salePrice", "网络标价", customer_visible_by_default=True),
            FieldSpec("carPriceInfo.wholesalePrice", "批发价", restricted_by_default=True),
            FieldSpec("carPriceInfo.managerPrice", "经理底价", restricted_by_default=True),
            FieldSpec("carPriceInfo.retrofitPrice", "加装费用", restricted_by_default=True),
        ),
    ),
    (
        "model_parameters",
        "车型参数",
        (
            FieldSpec("carModelParam.highlightsConfiguration", "亮点配置", customer_visible_by_default=True),
            FieldSpec("carModelParam.engineNumber", "发动机号", restricted_by_default=True),
            FieldSpec("carModelParam.carBody", "车身结构", customer_visible_by_default=True),
            FieldSpec("carModelParam.gearBoxType", "变速箱类型", customer_visible_by_default=True),
            FieldSpec("carModelParam.seatNumber", "座位数", customer_visible_by_default=True),
            FieldSpec("carModelParam.engineVolumeLiter", "排量（L）", customer_visible_by_default=True),
            FieldSpec("carModelParam.emissionStandard", "排放标准", customer_visible_by_default=True),
            FieldSpec("carModelParam.fuelType", "燃料形式", customer_visible_by_default=True),
        ),
    ),
    (
        "license_information",
        "牌证信息",
        (
            FieldSpec("carLicenseInfo.xiancheshangyexianjine", "商业险金额"),
            FieldSpec("carLicenseInfo.xiancheshangyexiandaoqiri", "商业险到期"),
            FieldSpec("carLicenseInfo.jiaoqiangdaoqiri", "交强险到期"),
            FieldSpec("carLicenseInfo.keysCount", "钥匙数量", customer_visible_by_default=True),
            FieldSpec("carLicenseInfo.transferTotal", "过户次数", customer_visible_by_default=True),
        ),
    ),
)


VEHICLE_PICTURE_FIELD_SPECS = (
    FieldSpec("carId", "关联车辆 ID"),
    FieldSpec("pictureName", "照片名称", customer_visible_by_default=True),
    FieldSpec("pictureNumber", "照片顺序编号", customer_visible_by_default=True),
    FieldSpec("pictureDescription", "照片描述", customer_visible_by_default=True),
    FieldSpec("pictureBig", "照片链接", customer_visible_by_default=True),
    FieldSpec("businessType", "业务类型", customer_visible_by_default=True),
)


VEHICLE_UPDATE_PARAM_FIELD_SPECS = (
    FieldSpec("updateParam.appId", "appId"),
    FieldSpec("updateParam.carId", "carId"),
    FieldSpec("updateParam.operator", "操作人"),
    FieldSpec("updateParam.assessor", "评估师"),
    FieldSpec("updateParam.baseCarInfo.vinNumber", "VIN 码"),
    FieldSpec("updateParam.baseCarInfo.name.brandCode", "品牌 code"),
    FieldSpec("updateParam.baseCarInfo.name.brandName", "品牌"),
    FieldSpec("updateParam.baseCarInfo.name.seriesCode", "车系 code"),
    FieldSpec("updateParam.baseCarInfo.name.seriesName", "车系"),
    FieldSpec("updateParam.baseCarInfo.name.modelCode", "车型 code"),
    FieldSpec("updateParam.baseCarInfo.name.modelName", "车型"),
    FieldSpec("updateParam.baseCarInfo.firstLicensePlateDate", "首次上牌时间"),
    FieldSpec("updateParam.baseCarInfo.area.cityCode", "车辆所在地城市 code"),
    FieldSpec("updateParam.baseCarInfo.area.cityName", "车辆所在地城市名"),
    FieldSpec("updateParam.baseCarInfo.area.provinceCode", "车辆所在地省份 code"),
    FieldSpec("updateParam.baseCarInfo.area.provinceName", "车辆所在地省份名"),
    FieldSpec("updateParam.baseCarInfo.area.displayValue", "车辆所在地展示值"),
    FieldSpec("updateParam.baseCarInfo.registerArea.cityCode", "车辆归属地城市 code"),
    FieldSpec("updateParam.baseCarInfo.registerArea.cityName", "车辆归属地城市名"),
    FieldSpec("updateParam.baseCarInfo.registerArea.provinceCode", "车辆归属地省份 code"),
    FieldSpec("updateParam.baseCarInfo.registerArea.provinceName", "车辆归属地省份名"),
    FieldSpec("updateParam.baseCarInfo.stockStatus", "库存状态"),
    FieldSpec("updateParam.baseCarInfo.contractSignDate", "采购日期"),
    FieldSpec("updateParam.baseCarInfo.vehicleCondition", "车况（对内）"),
    FieldSpec("updateParam.baseCarInfo.carDetailForDisplay", "车辆描述（对外）"),
    FieldSpec("updateParam.baseCarInfo.color", "车身颜色"),
    FieldSpec("updateParam.baseCarInfo.innerColor", "内饰颜色"),
    FieldSpec("updateParam.baseCarInfo.productionDate", "出厂日期"),
    FieldSpec("updateParam.baseCarInfo.annualExpiresDate", "年检到期日"),
    FieldSpec("updateParam.baseCarInfo.outStockDate", "退库日期"),
    FieldSpec("updateParam.baseCarInfo.inStock", "入库日期"),
    FieldSpec("updateParam.baseCarInfo.reserveTime", "预定日期"),
    FieldSpec("updateParam.baseCarInfo.payTime", "销售日期"),
    FieldSpec("updateParam.baseCarInfo.mileage", "表显里程（公里）"),
    FieldSpec("updateParam.baseCarInfo.outStockReason", "退库原因"),
    FieldSpec("updateParam.baseCarInfo.outStockReasonRemarks", "退库原因备注"),
    FieldSpec("updateParam.baseCarInfo.salesperson", "销售员"),
    FieldSpec("updateParam.baseCarInfo.useType", "使用性质"),
    FieldSpec("updateParam.baseCarInfo.plateNumber", "车牌号"),
    FieldSpec("updateParam.baseCarInfo.carRemark", "备注"),
    FieldSpec("updateParam.baseCarInfo.vehicleNumber", "车辆编号"),
    FieldSpec("updateParam.baseCarInfo.purchaseType", "采购类型"),
    FieldSpec("updateParam.baseCarInfo.assessmentPhotoList", "评估采购资料照片"),
    FieldSpec("updateParam.baseCarInfo.video", "车辆视频"),
    FieldSpec("updateParam.baseCarInfo.video.coverPictureUrl", "视频封面"),
    FieldSpec("updateParam.baseCarInfo.video.url", "视频地址"),
    FieldSpec("updateParam.baseCarInfo.weidianIsUpshelf", "微店上架状态"),
    FieldSpec("updateParam.baseCarInfo.upShelfDate", "微店上架时间"),
    FieldSpec("updateParam.baseCarInfo.downShelfDate", "微店下架时间"),
    FieldSpec("updateParam.baseCarInfo.detectReportPdf.url", "检测报告地址"),
    FieldSpec("updateParam.baseCarInfo.detectReportPdf.name", "检测报告名称"),
    FieldSpec("updateParam.carOwnerInfo.payee", "收款人"),
    FieldSpec("updateParam.carOwnerInfo.address", "地址（车主信息）"),
    FieldSpec("updateParam.carOwnerInfo.bankId", "银行卡号"),
    FieldSpec("updateParam.carOwnerInfo.identify", "身份证号"),
    FieldSpec("updateParam.carOwnerInfo.phoneNumber", "手机号码"),
    FieldSpec("updateParam.carOwnerInfo.purchaseTax", "购置税"),
    FieldSpec("updateParam.carOwnerInfo.customerName", "车主姓名"),
    FieldSpec("updateParam.carOwnerInfo.customerType", "客户类型"),
    FieldSpec("updateParam.carOwnerInfo.otherAccount", "其他账户"),
    FieldSpec("updateParam.carOwnerInfo.purchaseSource", "采购来源"),
    FieldSpec("updateParam.carOwnerInfo.openAccountBank", "开户行"),
    FieldSpec("updateParam.carPriceInfo.purchasePrice", "采购价"),
    FieldSpec("updateParam.carPriceInfo.newPrice", "新车指导价"),
    FieldSpec("updateParam.carPriceInfo.dealPrice", "成交价"),
    FieldSpec("updateParam.carPriceInfo.exhibitionPrice", "展厅标价"),
    FieldSpec("updateParam.carPriceInfo.salesPrice", "销售底价"),
    FieldSpec("updateParam.carPriceInfo.salePrice", "网络标价"),
    FieldSpec("updateParam.carPriceInfo.wholesalePrice", "批发价"),
    FieldSpec("updateParam.carPriceInfo.managerPrice", "经理底价"),
    FieldSpec("updateParam.carPriceInfo.retrofitPrice", "加装费用"),
    FieldSpec("updateParam.carModelParam.engineNumber", "发动机号"),
    FieldSpec("updateParam.carModelParam.highlightsConfiguration", "亮点配置"),
    FieldSpec("updateParam.carModelParam.carBody", "车身结构"),
    FieldSpec("updateParam.carModelParam.gearBoxType", "变速箱类型"),
    FieldSpec("updateParam.carModelParam.seatNumber", "座位数"),
    FieldSpec("updateParam.carModelParam.engineVolumeLiter", "排量（L）"),
    FieldSpec("updateParam.carModelParam.emissionStandard", "排放标准"),
    FieldSpec("updateParam.carModelParam.fuelType", "燃料形式"),
    FieldSpec("updateParam.carLicenseInfo.xiancheshangyexianjine", "商业险金额"),
    FieldSpec("updateParam.carLicenseInfo.xiancheshangyexiandaoqiri", "商业险到期"),
    FieldSpec("updateParam.carLicenseInfo.jiaoqiangdaoqiri", "交强险到期"),
    FieldSpec("updateParam.carLicenseInfo.keysCount", "钥匙数量"),
    FieldSpec("updateParam.carLicenseInfo.transferTotal", "过户次数"),
)


CUSTOMER_DETAIL_FIELD_SPECS = (
    FieldSpec("appId", "appId", restricted_by_default=True),
    FieldSpec("operator", "操作人", restricted_by_default=True),
    FieldSpec("phone", "手机号", restricted_by_default=True),
    FieldSpec("weichat", "微信号", restricted_by_default=True),
    FieldSpec("owner", "销售", restricted_by_default=True),
    FieldSpec("creator", "客户创建人", restricted_by_default=True),
    FieldSpec("phoneArea.cityCode", "手机号归属地城市 code", restricted_by_default=True),
    FieldSpec("phoneArea.cityName", "手机号归属地城市名", restricted_by_default=True),
    FieldSpec("phoneArea.provinceCode", "手机号归属地省份 code", restricted_by_default=True),
    FieldSpec("phoneArea.provinceName", "手机号归属地省份名", restricted_by_default=True),
    FieldSpec("phoneArea.displayValue", "手机号归属地展示值", restricted_by_default=True),
    FieldSpec("douyin", "抖音号", restricted_by_default=True),
    FieldSpec("grade", "意向等级", restricted_by_default=True),
    FieldSpec("transactionRemarks", "成交备注", restricted_by_default=True),
    FieldSpec("lastFollowUpTime", "最近跟进时间", restricted_by_default=True),
    FieldSpec("nextFollowUpTime", "下次跟进时间", restricted_by_default=True),
    FieldSpec("source", "客户来源", restricted_by_default=True),
    FieldSpec("customerOperator", "客户运营", restricted_by_default=True),
    FieldSpec("operationPhase", "客户业务阶段", restricted_by_default=True),
    FieldSpec("forecastTime", "预计买车时间", restricted_by_default=True),
    FieldSpec("gender", "性别", restricted_by_default=True),
    FieldSpec("name", "姓名", restricted_by_default=True),
    FieldSpec("sellMile", "卖车里程", restricted_by_default=True),
    FieldSpec("birthday", "生日", restricted_by_default=True),
    FieldSpec("sellLicensePlateDate", "卖车上牌时间", restricted_by_default=True),
    FieldSpec("payTime", "成交时间", restricted_by_default=True),
    FieldSpec("reserveTime", "预定时间", restricted_by_default=True),
    FieldSpec("failureTime", "战败时间", restricted_by_default=True),
    FieldSpec("invalidTime", "无效时间", restricted_by_default=True),
    FieldSpec("dateCreate", "创建时间", restricted_by_default=True),
    FieldSpec("dateUpdate", "更新时间", restricted_by_default=True),
    FieldSpec("budgetUp", "最高预算", restricted_by_default=True),
    FieldSpec("budgetLow", "最低预算", restricted_by_default=True),
    FieldSpec("transactionTime", "成交次数", restricted_by_default=True),
    FieldSpec("inviteTime", "邀约次数", restricted_by_default=True),
    FieldSpec("arrivalTime", "到店次数", restricted_by_default=True),
    FieldSpec("intent", "意向描述", restricted_by_default=True),
    FieldSpec("lastContent", "最近跟进内容", restricted_by_default=True),
    FieldSpec("shopCode", "门店", restricted_by_default=True),
    FieldSpec("intentCarType", "意向车系", restricted_by_default=True),
    FieldSpec("failureReason", "战败原因", restricted_by_default=True),
    FieldSpec("invalidReason", "无效原因", restricted_by_default=True),
    FieldSpec("phoneBackup", "备用号", restricted_by_default=True),
    FieldSpec("address", "联系地址", restricted_by_default=True),
    FieldSpec("hobby", "兴趣", restricted_by_default=True),
    FieldSpec("leadSource", "线索来源", restricted_by_default=True),
    FieldSpec("identityCard", "身份证号", restricted_by_default=True),
    FieldSpec("profession", "职业", restricted_by_default=True),
    FieldSpec("sellRemarks", "备注", restricted_by_default=True),
    FieldSpec("isImportant", "是否重点客户", restricted_by_default=True),
    FieldSpec("businessType", "业务类型", restricted_by_default=True),
    FieldSpec("sellBrandSeries.brandCode", "出售品牌 code", restricted_by_default=True),
    FieldSpec("sellBrandSeries.brandName", "出售品牌", restricted_by_default=True),
    FieldSpec("sellBrandSeries.seriesCode", "出售车系 code", restricted_by_default=True),
    FieldSpec("sellBrandSeries.seriesName", "出售车系", restricted_by_default=True),
    FieldSpec("sellBrandSeries.modelCode", "出售车型 code", restricted_by_default=True),
    FieldSpec("sellBrandSeries.modelName", "出售车型", restricted_by_default=True),
    FieldSpec("isSellCar", "是否卖车", restricted_by_default=True),
    FieldSpec("followUpStatus", "回访状态", restricted_by_default=True),
    FieldSpec("concern", "关注点", restricted_by_default=True),
    FieldSpec("carStructure", "车体形式", restricted_by_default=True),
    FieldSpec("carAge", "车龄", restricted_by_default=True),
    FieldSpec("introducer", "老客户介绍人", restricted_by_default=True),
    FieldSpec("photoAlbum", "相册", restricted_by_default=True),
    FieldSpec("location.cityCode", "所在地城市 code", restricted_by_default=True),
    FieldSpec("location.cityName", "所在地城市名", restricted_by_default=True),
    FieldSpec("location.provinceCode", "所在地省份 code", restricted_by_default=True),
    FieldSpec("location.provinceName", "所在地省份名", restricted_by_default=True),
    FieldSpec("location.displayValue", "所在地展示值", restricted_by_default=True),
    FieldSpec("createType", "客户创建方式", restricted_by_default=True),
    FieldSpec("recordId", "recordId", restricted_by_default=True),
)

CUSTOMER_UPDATE_PARAM_FIELD_SPECS = tuple(
    FieldSpec(
        f"updateParam.{spec.path}",
        spec.label,
        customer_visible_by_default=False,
        restricted_by_default=True,
    )
    for spec in CUSTOMER_DETAIL_FIELD_SPECS
)


OFFICIAL_CUSTOMER_API_NAME_STATUS = {
    "customer_detail": "document_section_present_but_api_name_missing",
    "customer_update": "document_section_present_but_api_name_missing",
}


def field_paths(specs: tuple[FieldSpec, ...]) -> frozenset[str]:
    return frozenset(spec.path for spec in specs)


def grouped_field_paths(groups: tuple[tuple[str, str, tuple[FieldSpec, ...]], ...]) -> frozenset[str]:
    return frozenset(spec.path for _group_id, _label, specs in groups for spec in specs)


VEHICLE_DETAIL_FIELD_PATHS = grouped_field_paths(VEHICLE_DETAIL_FIELD_GROUP_SPECS)
VEHICLE_PICTURE_FIELD_PATHS = field_paths(VEHICLE_PICTURE_FIELD_SPECS)
VEHICLE_UPDATE_PARAM_FIELD_PATHS = field_paths(VEHICLE_UPDATE_PARAM_FIELD_SPECS)
CUSTOMER_DETAIL_FIELD_PATHS = field_paths(CUSTOMER_DETAIL_FIELD_SPECS)
CUSTOMER_UPDATE_PARAM_FIELD_PATHS = field_paths(CUSTOMER_UPDATE_PARAM_FIELD_SPECS)
VEHICLE_CUSTOMER_VISIBLE_FIELD_PATHS = frozenset(
    spec.path
    for _group_id, _label, specs in VEHICLE_DETAIL_FIELD_GROUP_SPECS
    for spec in specs
    if spec.customer_visible_by_default
)
VEHICLE_RESTRICTED_FIELD_PATHS = frozenset(
    spec.path
    for _group_id, _label, specs in VEHICLE_DETAIL_FIELD_GROUP_SPECS
    for spec in specs
    if spec.restricted_by_default
)
CUSTOMER_RESTRICTED_FIELD_PATHS = frozenset(spec.path for spec in CUSTOMER_DETAIL_FIELD_SPECS if spec.restricted_by_default)
CUSTOMER_UPDATE_RESTRICTED_FIELD_PATHS = frozenset(spec.path for spec in CUSTOMER_UPDATE_PARAM_FIELD_SPECS if spec.restricted_by_default)
