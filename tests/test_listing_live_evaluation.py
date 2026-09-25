from datetime import datetime, timezone, timedelta
import pytest
from evaluation.listing_live import ExpectedListing, differences


def test_partial_extraction_cannot_pass():
    expected={'asking_price':600000000,'area_sqm':84.9,'address':'서울 노원구 상계동 1'}
    assert set(differences(expected,{'asking_price':600000000}))=={'area_sqm','address'}
    assert not differences(expected,dict(expected))
    assert 'asking_price' in differences(expected,{**expected,'asking_price':600000001})


def test_old_or_incomplete_gold_is_rejected():
    row={'id':'manual','url':'https://fin.land.naver.com/articles/123456','reviewed_at':datetime.now(timezone.utc)-timedelta(days=2),
         'expected':{'asking_price':600000000,'area_sqm':84.9,'address':'검증주소'}}
    with pytest.raises(ValueError):ExpectedListing.model_validate(row)
    row['reviewed_at']=datetime.now(timezone.utc)
    row['expected']={'asking_price':600000000}
    with pytest.raises(ValueError):ExpectedListing.model_validate(row)
