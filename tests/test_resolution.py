from footpred.infra.memory import InMemoryUnitOfWork
from footpred.ingest.resolution import TeamResolver, normalize_name


def test_normalize_folds_accents_case_punctuation():
    assert normalize_name("  Köln FC. ") == "koln fc"
    assert normalize_name("SAINT-ÉTIENNE") == "saint etienne"
    assert normalize_name("Real   Madrid") == "real madrid"


def test_created_then_exact_then_alias():
    uow = InMemoryUnitOfWork()
    r = TeamResolver(uow, source="test")

    first = r.resolve("Real Madrid")
    assert first.kind == "created"

    again = r.resolve("real  MADRID")  # same normalized form
    assert again.kind == "created" or again.team_id == first.team_id
    assert again.team_id == first.team_id

    # a fresh resolver (new import session) hits the persisted team exactly
    r2 = TeamResolver(uow, source="test2")
    hit = r2.resolve("Real Madrid")
    assert hit.kind == "exact" and hit.team_id == first.team_id


def test_fuzzy_match_persists_alias_and_is_remembered():
    uow = InMemoryUnitOfWork()
    r = TeamResolver(uow, source="test")
    base = r.resolve("Real Madrid")

    fuzzy = r.resolve("Real Madridd")  # ratio ~0.956 >= 0.92
    assert fuzzy.kind == "fuzzy"
    assert fuzzy.team_id == base.team_id
    assert fuzzy.confidence >= 0.92

    # alias was persisted: a NEW resolver resolves it via the alias table
    r2 = TeamResolver(uow, source="later")
    hit = r2.resolve("Real Madridd")
    assert hit.kind == "alias" and hit.team_id == base.team_id


def test_dissimilar_name_creates_new_team_not_false_merge():
    uow = InMemoryUnitOfWork()
    r = TeamResolver(uow, source="test")
    a = r.resolve("Arsenal")
    b = r.resolve("Aston Villa")
    assert b.kind == "created"
    assert a.team_id != b.team_id
