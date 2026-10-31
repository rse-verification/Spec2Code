import pytest

from spec2code.pipeline_modules.critics.critics_registry import GUI_CRITICS_CATALOG, CRITIC_BUILDERS


@pytest.mark.unit
def test_gui_critic_defaults_align_with_verify_expectations():
    by_name = {c["name"]: c for c in GUI_CRITICS_CATALOG}

    framac_opts = {o["key"]: o for o in by_name["framac-wp"]["options"]}
    misra_opts = {o["key"]: o for o in by_name["cppcheck-misra"]["options"]}

    # The public GUI policy matches FramaCWPCritic's 60s process / 2s goal defaults.
    assert framac_opts["timeout"]["default"] == 60
    assert framac_opts["wp_timeout"]["default"] == 2
    assert framac_opts["framac_wp_no_qed"]["default"] is False
    assert framac_opts["framac_wp_no_split_switch"]["default"] is False
    assert misra_opts["timeout"]["default"] == 120
    assert misra_opts["cppcheck_enable_all"]["default"] is False
    assert misra_opts["cppcheck_jobs"]["default"] == 0
    assert misra_opts["cppcheck_gate_warnings"]["default"] is True


@pytest.mark.unit
def test_gui_framac_defaults_and_overrides_reach_the_runtime_critic():
    catalog = next(c for c in GUI_CRITICS_CATALOG if c["name"] == "framac-wp")
    defaults = {option["key"]: option["default"] for option in catalog["options"]}
    critic = CRITIC_BUILDERS["framac-wp"](defaults, [], 999)
    assert critic.timeout == 60
    assert critic.wp_timeout == 2
    override = CRITIC_BUILDERS["framac-wp"]({**defaults, "timeout": 180, "wp_timeout": 5}, [], 999)
    assert override.timeout == 180
    assert override.wp_timeout == 5
