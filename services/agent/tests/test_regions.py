"""地方名を地名に広げて照合する（全国対応）。"""

from __future__ import annotations

from event_agent.domain.regions import KNOWN_LOCATIONS, in_locations, places_for


def test_region_names_expand_to_prefectures_and_cities():
    assert in_locations("福岡県福岡市博多区", ["九州"])
    assert in_locations("宮城県仙台市青葉区", ["東北"])
    assert in_locations("大阪府大阪市北区", ["関西"])
    assert not in_locations("東京都渋谷区", ["関西"])


def test_city_names_match_as_they_are():
    assert places_for("名古屋") == ("名古屋",)
    assert in_locations("愛知県名古屋市中村区", ["名古屋"])


def test_every_region_is_a_known_location():
    for region in ("北海道", "東北", "関東", "中部", "関西", "中国", "四国", "九州", "沖縄"):
        assert region in KNOWN_LOCATIONS
