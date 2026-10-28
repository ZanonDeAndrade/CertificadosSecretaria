"""Per-work certificates (the Mostra) as the panel and the public site list them.

A per-work certificate is valid for every author, so every listing names it by
its work and all of its authors, and a name search finds it by any author.
The listing reads what emission already stored (``authors_json``); a finished
batch names each work in its response only, never in the stored result.
Ordinary certificates keep their holder view.
"""

from __future__ import annotations

import importlib.util
import io
import json
import uuid
from itertools import count
from pathlib import Path

import pandas as pd
import pytest
from certificados_backend.services import batch_service
from fastapi.testclient import TestClient

from database import db

_REPO_ROOT = Path(__file__).resolve().parents[3]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MOSTRA = "scientific_initiation"
EVENT = "Mostra de Iniciação Científica 2026"
AUTHORS = (
    "Pessoa Exemplo Alfa",
    "Pessoa Exemplo Beta",
    "Pessoa Exemplo Gama",
    "Pessoa Exemplo Delta",
    "Pessoa Exemplo Épsilon",
    "Pessoa Exemplo Zeta",
    "Pessoa Exemplo Eta",
    "Pessoa Exemplo Teta",
)
# Title → its authors: one, three and eight, the supported maximum.
WORKS = {
    "Compostagem doméstica": AUTHORS[:1],
    "Horta vertical automatizada": AUTHORS[:3],
    "Robô seguidor de linha": AUTHORS,
}
ORDINARY_CODE = "CERT-2026-COMUM01"
_KEYS = count(1)


def _work(title: str, authors: tuple[str, ...]) -> dict:
    row: dict = {f"autor{index}": "" for index in range(1, 9)}
    row.update({f"autor{index}": name for index, name in enumerate(authors, start=1)})
    row.update(
        evento=EVENT,
        titulo_trabalho=title,
        equipe="Equipe Verde",
        carga_horaria="",
        data_emissao="10/06/2026",
        data_inicio="",
        data_fim="",
    )
    return row


def _start(client) -> dict:
    """Start the Mostra batch; the response carries the idempotency key used."""
    key = f"per-work-listing-{next(_KEYS):06d}"
    buffer = io.BytesIO()
    pd.DataFrame([_work(title, authors) for title, authors in WORKS.items()]).to_excel(
        buffer, index=False
    )
    started = client.post(
        "/emission-batches",
        files={"file": ("lote.xlsx", buffer.getvalue(), XLSX_MIME)},
        data={"texto_padrao": "", "certificate_type": MOSTRA, "drive_folders_json": "{}"},
        headers={"Idempotency-Key": key},
    )
    assert started.status_code == 202, started.text
    return {**started.json(), "idempotency_key": key}


@pytest.fixture
def issued(client, auth_headers, mostra_template) -> dict:
    """A finished Mostra batch with 1, 3 and 8 authors, plus one ordinary
    certificate that happens to carry a work title (an optional column)."""
    batch = _start(client)
    db.insert_certificates(
        [
            {
                "unique_code": ORDINARY_CODE,
                "participant_name": "Ana Comum",
                "event_name": "Semana Acadêmica",
                "certificate_type": "speaker",
                "work_title": "Palestra de abertura",
                "issue_date": "2026-06-10",
                "status": "ativo",
            }
        ]
    )
    return batch


def _by_title(items: list[dict]) -> dict[str, dict]:
    return {item["work_title"]: item for item in items if item["certificate_type"] == MOSTRA}


def test_listing_detail_and_dashboard_name_the_work_and_every_author_in_order(client, issued):
    listed = client.get("/certificates").json()["items"]
    works = _by_title(listed)
    assert set(works) == set(WORKS)
    recent = _by_title(client.get("/admin/recent-certificates").json())
    for title, authors in WORKS.items():
        for item in (
            works[title],
            client.get(f"/certificates/{works[title]['unique_code']}").json(),
            recent[title],
        ):
            assert item["authors"] == list(authors)
            assert item["work_title"] == title
            assert item["team_name"] == "Equipe Verde"
            # The holder stays the first author, as stored.
            assert item["participant_name"] == authors[0]

    ordinary = next(item for item in listed if item["unique_code"] == ORDINARY_CODE)
    assert ordinary["participant_name"] == "Ana Comum"
    assert ordinary["authors"] == []


def test_name_search_finds_a_work_by_any_author_partially_and_without_accents(client, issued):
    def titles(name: str) -> set[str]:
        items = client.get("/certificates", params={"name": name}).json()["items"]
        return {item["work_title"] or item["participant_name"] for item in items}

    for name in AUTHORS:
        assert titles(name) == {title for title, authors in WORKS.items() if name in authors}, name
    # Part of a name, any case, no accents: the eighth work alone has these.
    assert titles("exemplo teta") == {"Robô seguidor de linha"}
    assert titles("PESSOA EXEMPLO EPSILON") == {"Robô seguidor de linha"}
    assert titles("  exemplo   épsilon ") == {"Robô seguidor de linha"}
    # One term never spans two authors.
    assert titles("Alfa Pessoa Exemplo Beta") == set()
    # Ordinary certificates are still found by their holder only.
    assert titles("ana comum") == {"Palestra de abertura"}
    assert titles("palestra") == set()


def test_finished_batch_names_each_work_only_in_the_response(client, issued):
    batch_id = issued["id"]
    for batch in (
        client.get(f"/emission-batches/{batch_id}").json(),
        client.get(f"/emission-batches/by-idempotency-key/{issued['idempotency_key']}").json(),
    ):
        assert batch["status"] == "completed", batch
        generated = sorted(batch["result"]["generated"], key=lambda entry: entry["row_number"])
        assert [entry["work_title"] for entry in generated] == list(WORKS)
        assert [entry["authors"] for entry in generated] == [list(a) for a in WORKS.values()]
        assert [entry["name"] for entry in generated] == [a[0] for a in WORKS.values()]

    stored = json.loads(db.get_emission_batch(batch_id)["result_json"])
    assert all(
        "work_title" not in entry and "authors" not in entry for entry in stored["generated"]
    )

    # The same works again are kept as duplicates, named the same way.
    again = client.get(f"/emission-batches/{_start(client)['id']}").json()
    assert again["duplicate_count"] == 3
    duplicates = sorted(again["result"]["duplicates"], key=lambda entry: entry["row_number"])
    assert [entry["work_title"] for entry in duplicates] == list(WORKS)
    assert [entry["authors"] for entry in duplicates] == [list(a) for a in WORKS.values()]


def test_work_details_leave_ordinary_and_unfinished_batches_untouched(monkeypatch):
    def no_lookup(codes):
        raise AssertionError("no certificate lookup expected")

    monkeypatch.setattr(db, "get_certificates_by_codes", no_lookup)
    result = {"generated": [{"row_number": 2, "name": "Ana Comum", "code": ORDINARY_CODE}]}
    ordinary = {"status": "completed", "certificate_type": "speaker", "result": result}
    running = {"status": "processing", "certificate_type": MOSTRA, "result": result}
    for batch in (ordinary, running):
        snapshot = json.dumps(batch, sort_keys=True)
        assert json.dumps(batch_service.with_work_details(batch), sort_keys=True) == snapshot


def _public_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+")
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v1")
    path = _REPO_ROOT / "certificados_consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(f"consulta_{uuid.uuid4().hex}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return TestClient(module.app)


def _results(page: str) -> str:
    """What each public search result shows. The search form and the download
    form of each result echo the term typed, so they are left out."""
    blocks = page.split('<div class="result-info">')[1:]
    assert blocks, "no search result"
    return "\n".join(block[: block.index("</div>")] for block in blocks)


def test_public_name_search_shows_the_title_and_masks_every_author(client, issued, monkeypatch):
    public = _public_client(monkeypatch)
    masked = [" ".join(f"{word[0]}•••" for word in name.split()) for name in AUTHORS]

    search = public.post("/public/search", json={"nome": AUTHORS[7]}).json()
    assert search["total"] == 1
    item = search["items"][0]
    assert item["work_title"] == "Robô seguidor de linha"
    assert item["authors"] == masked

    page = _results(public.post("/", data={"nome": AUTHORS[7]}).text)
    assert "<h3>Robô seguidor de linha</h3>" in page
    assert "Autores: " + ", ".join(masked) in page
    for name in AUTHORS:
        assert name not in page

    single = _results(public.post("/", data={"nome": "Pessoa Exemplo Alfa"}).text)
    assert "Autor: P••• E••• A•••" in single

    # Ordinary results keep the masked holder; their optional title stays out.
    ordinary = public.post("/public/search", json={"nome": "Ana Comum"}).json()["items"][0]
    assert ordinary["participant_name"] == "A••• C•••"
    assert ordinary["work_title"] is None
    ordinary_page = _results(public.post("/", data={"nome": "Ana Comum"}).text)
    assert "<h3>A••• C•••</h3>" in ordinary_page
    assert "Palestra de abertura" not in ordinary_page
