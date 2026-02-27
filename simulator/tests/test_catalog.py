from pathlib import Path

from helpdesk_sim.services.catalog_service import CatalogService


def test_catalog_loads_profiles_and_scenarios() -> None:
    templates = Path(__file__).resolve().parents[1] / "src" / "helpdesk_sim" / "templates"
    catalog = CatalogService(templates_dir=templates)
    catalog.load()

    profiles = catalog.list_profiles()
    assert "normal_day" in profiles
    assert "busy_day" in profiles

    profile = catalog.get_profile("normal_day")
    scenario = catalog.pick_scenario(tier=list(profile.tier_weights.keys())[0])
    assert scenario.id
