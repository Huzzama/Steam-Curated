import json

import data.repository as repo
import data.purchase_repository as prepo
from data.models import Purchase
from tests.conftest import sample_games


def test_add_many_and_lookup(data_dir):
    added = repo.add_many(sample_games())
    assert len(added) == 3
    assert repo.exists("1245620")
    assert repo.get_by_app_id("504230").status == "Purchased"
    assert {g.id for g in repo.get_all()} == {1, 2, 3}
    assert len(repo.get_on_sale()) == 2


def test_atomic_write_keeps_backup(data_dir):
    repo.add_many(sample_games()[:1])
    repo.add_many(sample_games()[1:2])
    assert (data_dir / "wishlist.json").exists()
    assert (data_dir / "wishlist.json.bak").exists()


def test_corrupt_file_recovers_from_backup(data_dir):
    repo.add_many(sample_games()[:1])
    repo.add_many(sample_games()[1:2])
    (data_dir / "wishlist.json").write_text("{not json", encoding="utf-8")
    repo._invalidate()
    names = {g.name for g in repo.get_all()}
    assert "Elden Ring" in names           # restored from .bak


def test_update_and_delete(data_dir):
    g = repo.add_many(sample_games()[:1])[0]
    g.priority = "B"
    assert repo.update(g)
    assert repo.get_by_id(g.id).priority == "B"
    assert repo.delete(g.id)
    assert repo.get_all() == []


def test_purchases_totals(data_dir):
    prepo.add(Purchase("1", "A", "2026-01-01", 10.0, 20.0, "USD", 50, "Standard", 10.0))
    prepo.add(Purchase("2", "B", "2026-02-01", 5.0, 5.0, "USD", 0, "Standard", 0.0))
    assert prepo.total_spent() == 15.0
    assert prepo.total_saved() == 10.0
    prepo.delete("1")
    assert len(prepo.get_all()) == 1
