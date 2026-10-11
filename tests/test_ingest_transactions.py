from backend.tools.ingest_transactions import _endpoints_for, _month_range, _recent_months
from xml.etree import ElementTree as ET
from price_engine import _parse_items


def test_month_range_crosses_year():
    assert _month_range("202511", "202602") == ["202511", "202512", "202601", "202602"]


def test_duplicate_source_endpoint_is_collected_once():
    endpoints = _endpoints_for(["상업용", "업무용"])
    assert len(endpoints) == 1


def test_recent_month_count():
    months = _recent_months(12)
    assert len(months) == 12
    assert months == sorted(months)


def test_parser_builds_legal_dong_code_from_request_region():
    item = ET.fromstring(
        "<item><dealAmount>100,000</dealAmount><excluUseAr>50</excluUseAr>"
        "<umdCd>103</umdCd><umdNm>역삼동</umdNm></item>"
    )
    row = _parse_items([item], "주거용", "아파트", "11680")[0]
    assert row["bjdong_code"] == "1168010300"


def test_row_house_parser_keeps_land_share_and_house_type():
    item = ET.fromstring(
        "<item><dealAmount>29,000</dealAmount><excluUseAr>40.95</excluUseAr><landAr>25.38</landAr>"
        "<houseType>다세대</houseType><jibun>593-63</jibun><mhouseNm>대림캐슬(593-63)</mhouseNm><umdNm>방화동</umdNm></item>"
    )
    row = _parse_items([item], "주거용", "연립다세대", "11500")[0]
    assert row["land_area_sqm"] == 25.38
    assert row["building_use"] == "다세대"
    assert row["jibun"] == "593-63"


def test_detached_parser_still_prefers_plottage_area():
    item = ET.fromstring(
        "<item><dealAmount>90,000</dealAmount><totalFloorAr>120</totalFloorAr><plottageAr>150.5</plottageAr>"
        "<landAr>1</landAr><umdNm>방화동</umdNm></item>"
    )
    assert _parse_items([item], "주거용", "단독다가구", "11500")[0]["land_area_sqm"] == 150.5
