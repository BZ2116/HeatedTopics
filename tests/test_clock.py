from datetime import datetime

import pytest

from heated_topics_v3.clock import SHANGHAI, business_date, is_before_daily_cutoff


def test_business_day_rolls_over_at_eight_am():
    assert business_date(datetime(2026, 7, 13, 7, 59, tzinfo=SHANGHAI)).isoformat() == "2026-07-12"
    assert business_date(datetime(2026, 7, 13, 8, 0, tzinfo=SHANGHAI)).isoformat() == "2026-07-13"


def test_cutoff_converts_aware_datetime_to_shanghai():
    assert is_before_daily_cutoff(datetime.fromisoformat("2026-07-12T23:59:00+00:00"))
    assert not is_before_daily_cutoff(datetime.fromisoformat("2026-07-13T00:00:00+00:00"))


@pytest.mark.parametrize("service", [business_date, is_before_daily_cutoff])
def test_clock_services_reject_naive_datetimes(service):
    with pytest.raises(ValueError, match="timezone-aware"):
        service(datetime(2026, 7, 13, 8, 0))
