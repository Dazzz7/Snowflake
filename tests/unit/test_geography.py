from app.catalog.geography import find_states, normalize_state_name


def test_california_fips_mapping():
    result = normalize_state_name("California")
    assert result is not None
    assert result.name == "California"
    assert result.fips_code == "06"


def test_preposition_in_does_not_match_indiana():
    result = find_states("What is the population in California?")
    assert [geo.name for geo in result] == ["California"]

