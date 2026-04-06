from pathlib import Path


def test_strategy_room_template_reuses_canonical_tasks_and_avoids_duplicates():
    template = Path("clawteam/templates/strategy-room.toml").read_text(encoding="utf-8")

    assert "Reuse the canonical template tasks that already exist for each specialist." in template
    assert "Do not create duplicate tasks for the same specialist role unless a real gap appears." in template
    assert "If you create any truly new follow-up task because the built-in template tasks are insufficient" in template
    assert 'Create focused tasks for each specialist via `clawteam task create {team_name} "[task]" -o [member]`' not in template
