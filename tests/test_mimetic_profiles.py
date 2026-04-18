from project_mimic.mimetic import jitter_profile_for_device, movement_profile_for_viewport


def test_jitter_profiles_are_distinct_between_desktop_and_mobile() -> None:
    desktop = jitter_profile_for_device("desktop")
    mobile = jitter_profile_for_device("mobile")

    assert desktop.name == "desktop"
    assert mobile.name == "mobile"
    assert mobile.amplitude_px > desktop.amplitude_px


def test_viewport_profile_selects_mobile_compact() -> None:
    profile = movement_profile_for_viewport(390, 844)

    assert profile.name == "mobile-compact"
    assert profile.step_count >= 14
    assert profile.jitter.name == "mobile"


def test_viewport_profile_selects_large_desktop() -> None:
    profile = movement_profile_for_viewport(2560, 1440)

    assert profile.name == "desktop-large"
    assert profile.step_count >= 12
    assert profile.jitter.name == "desktop"
