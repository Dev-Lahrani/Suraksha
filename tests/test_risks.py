"""Risk engine tests (pure functions, no DB)."""

from suraksha.core.risks import (
    aqi_from_pm25,
    air_score,
    band,
    compute_risk_for_day,
    flood_score,
    heat_index_c,
    heat_score,
)


def test_heat_index_mild_conditions():
    # 25°C @ 50% RH → simple formula, slightly above ambient
    hi = heat_index_c(25, 50)
    assert 22 <= hi <= 30


def test_heat_index_extreme_conditions():
    # 40°C @ 50% RH is dangerously hot: HI must exceed 45°C
    hi = heat_index_c(40, 50)
    assert 45 <= hi <= 70


def test_heat_score_bands():
    res = heat_score(tmax=44.0, tavg=38.0, humidity=60.0)
    assert res["band"] in ("high", "moderate")
    assert res["score"] > 25
    res2 = heat_score(tmax=30.0, tavg=28.0, humidity=40.0)
    assert res2["band"] == "low"


def test_heat_score_missing_data_is_unknown():
    res = heat_score(None, None, None)
    assert res["band"] == "unknown"
    assert res["score"] is None


def test_flood_score_cloudburst_is_high():
    res = flood_score(rain_today=120.0, rain_3day=200.0, rain_p90=20.0)
    assert res["band"] == "high"
    assert res["score"] >= 80
    assert res["detail"]["ratio_vs_normal_heavy"] > 3


def test_flood_score_dry_day_is_low():
    res = flood_score(rain_today=0.0, rain_3day=2.0, rain_p90=25.0)
    assert res["band"] == "low"


def test_flood_score_missing_3day_is_unknown():
    assert flood_score(5.0, None, 20.0)["band"] == "unknown"


def test_aqi_breakpoints():
    assert aqi_from_pm25(0.0) == 0
    assert aqi_from_pm25(9.0) == 50
    assert aqi_from_pm25(35.5) == 101
    assert aqi_from_pm25(500.0) == 500


def test_air_score_unhealthy():
    res = air_score(pm25=130.0)  # AQI ≈ 187 → score ≈ 93
    assert res["band"] == "high"
    assert res["detail"]["aqi_us_epa"] > 150


def test_band_thresholds():
    assert band(None) == "unknown"
    assert band(10) == "low"
    assert band(30) == "moderate"
    assert band(70) == "high"


def test_compute_all_hazards():
    out = compute_risk_for_day(
        tmax=41, tavg=36, precipitation=90, rain_3day=150, rain_p90=20, humidity=55, pm25=60
    )
    assert set(out) == {"heat", "flood", "air"}
    assert out["flood"]["band"] == "high"
