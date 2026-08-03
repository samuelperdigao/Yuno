from types import SimpleNamespace

from app.farm_tickets import weekly_ranking


def entry(values: dict[str, int], status: str = "registrado") -> SimpleNamespace:
    return SimpleNamespace(values=values, status=status)


def ticket(user_id: str, name: str, entries: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        member_name=name,
        goal_items=[{"name": "Folha", "quantity": 100}],
        entries=entries,
    )


def test_ranking_ordena_por_total_e_ignora_entrada_em_revisao() -> None:
    ranking = weekly_ranking(
        [
            ticket("1", "Ana", [entry({"Folha": 60})]),
            ticket("2", "Bia", [entry({"Folha": 80}), entry({"Folha": 100}, "revisao")]),
        ]
    )

    assert [item["user_id"] for item in ranking] == ["2", "1"]
    assert ranking[0]["delivered_total"] == 80
    assert ranking[0]["completion_percent"] == 80


def test_ranking_agrega_multiplos_tickets_do_mesmo_membro() -> None:
    ranking = weekly_ranking(
        [
            ticket("1", "Ana", [entry({"Folha": 40})]),
            ticket("1", "Ana", [entry({"Folha": 60})]),
        ]
    )

    assert len(ranking) == 1
    assert ranking[0]["delivered_total"] == 100
    assert ranking[0]["completion_percent"] == 100
    assert ranking[0]["entry_count"] == 2
