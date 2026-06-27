from sf365_bugbounty_mcp import formatting as fmt


def test_money_formats_rubles_with_spaces():
    assert fmt.money(250000, "rub") == "250 000 ₽"
    assert fmt.money(None, "rub") == "—"


def test_program_url_uses_slug():
    assert fmt.program_url("vkontakte_vk").endswith("/programs/vkontakte_vk")


def test_scope_summary_splits_multi_asset_block():
    scopes = [
        {
            "appTypeName": "Domain",
            "severity": "critical",
            "id": 1,
            "scope": "a.example\n\nb.example\n\nc.example",
        }
    ]
    out = fmt.scope_summary(scopes, 106)
    assert "- a.example" in out
    assert "- b.example" in out
    assert "Domain" in out


def test_rewards_summary_orders_severity_high_first():
    rewards = {
        "currency": "rub",
        "onlyMaxPayment": False,
        "low": {"minReward": 0, "maxReward": 5000},
        "critical": {"minReward": 120000, "maxReward": 250000},
    }
    out = fmt.rewards_summary(rewards, 106)
    assert out.index("critical") < out.index("low")
    assert "250 000 ₽" in out


def test_programs_summary_handles_empty():
    out = fmt.programs_summary({"items": [], "page": 1, "total": 1, "totalEntries": 0})
    assert "No programs found" in out


def test_disclosed_list_summary():
    env = {
        "items": [
            {
                "reportDiscloseInfo": {"id": 1, "reportName": "XSS", "programName": "Acme"},
                "severity": "high",
                "amount": 50000.0,
                "currency": "rub",
                "author": {"username": "neo"},
            }
        ],
        "page": 1,
        "totalEntries": 1,
    }
    out = fmt.disclosed_list_summary(env)
    assert "XSS" in out and "neo" in out and "Acme" in out
