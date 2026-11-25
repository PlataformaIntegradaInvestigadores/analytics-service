"""Compose corpus audit, exploratory forecast review and real topic comparison."""

import argparse
import csv
import html
import importlib.metadata
import json
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.json_io import read_json_file
from app.core.provenance import sha256_file, source_files
from app.data.documents import read_database
from app.data.research_audit import audit_snapshot
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.domain.forecast_review import candidates, compare_annual, error_breakdown
from app.topic_review import compare_topics

REQUIREMENTS = ["R08", "R09", "R10", "R11", "R12", "R13", "R14", "R22", "R23"]


def trace_contract(snapshot, backlog, plan):
    if (
        snapshot.get("organization") != "centinela-jairo-quispe"
        or snapshot.get("project") != "Centinela-Analitica-Jairo"
        or snapshot.get("process") != "CMMI"
    ):
        raise AnalyticsError(
            "azure_contract_mismatch", "Expected actual Centinela CMMI snapshot"
        )
    remote = {item["id"]: item for item in snapshot["items"]}
    contract = []
    for item in backlog["items"]:
        if item["code"] not in REQUIREMENTS and item.get("parent") not in REQUIREMENTS:
            continue
        actual = remote.get(item["remote_id"])
        if (
            actual is None
            or not actual["fields"]["System.Title"].startswith("[" + item["code"] + "]")
            or actual["fields"]["System.TeamProject"] != snapshot["project"]
            or actual["fields"]["System.WorkItemType"] != item["type"]
        ):
            raise AnalyticsError("azure_item_mismatch", item["code"])
        fields = actual["fields"]
        parent_code = item.get("parent")
        if parent_code:
            parent_id = next(
                x["remote_id"] for x in backlog["items"] if x["code"] == parent_code
            )
            if not any(
                r["rel"] == "System.LinkTypes.Hierarchy-Reverse"
                and r["url"].endswith("/" + str(parent_id))
                for r in actual.get("relations", [])
            ):
                raise AnalyticsError("azure_hierarchy_mismatch", item["code"])
        contract.append(
            {
                "code": item["code"],
                "id": actual["id"],
                "type": item["type"],
                "parent_code": parent_code,
                "revision_read": actual["rev"],
                "state_read": fields["System.State"],
                "title": fields["System.Title"],
                "remote_description_sha256": fingerprint(
                    fields.get("System.Description", "")
                ),
                "remote_description_html": fields.get("System.Description", ""),
                "acceptance_criteria_local": item.get("acceptance_criteria", []),
                "url": (
                    "https://dev.azure.com/centinela-jairo-quispe/Centinela-Anali"
                    "tica-Jairo/_workitems/edit/"
                )
                + str(actual["id"]),
            }
        )
    if len([x for x in contract if x["type"] == "Requirement"]) != len(REQUIREMENTS):
        raise AnalyticsError(
            "azure_contract_incomplete", "All mapped requirements required"
        )
    return {
        "organization": snapshot["organization"],
        "project": snapshot["project"],
        "process": "CMMI",
        "plan_sha256": sha256_file(plan),
        "plan_pages": [2, 3, 4],
        "plan_objectives": {
            "priority_1": [4, 6],
            "priority_2": [4, 6],
            "priority_3": [2, 3, 6],
        },
        "items": contract,
        "state_policy": "Evidence does not automatically close requirements",
        "scope_precedence": (
            "Signed plan; real-participant evaluation retained by user/tu"
            "tor agreement. Historical CR01 is not approval to remove it."
        ),
    }


def _write(path, value):
    path.write_text(canonical_json(value), encoding="utf-8")


def render_report(report):
    def table(headers, rows):
        return (
            "<table><thead><tr>"
            + "".join("<th>" + html.escape(str(h)) + "</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>"
                + "".join("<td>" + html.escape(str(v)) + "</td>" for v in row)
                + "</tr>"
                for row in rows
            )
            + "</tbody></table>"
        )

    f, t, a = report["forecast"], report["topics"], report["audit"]
    body = (
        "<h1>Evaluación de tres prioridades con datos reales</h1><p>Ejecución: "
        + report["run_id"]
        + (
            "</p><p>Diagnóstico del pronóstico, comparación de temas y au"
            "ditoría. Los resultados de 2019–2021 ya se habían observado:"
            " las nuevas comparaciones son exploratorias y no una prueba "
            "final intacta.</p>"
        )
    )
    body += "<h2>1. Error del predictor anterior</h2>" + table(
        ["Tema", "MAE", "Sesgo (predicho−real)", "Observado", "Predicho"],
        [
            [
                r["key"],
                round(r["mae"], 4),
                round(r["bias"], 4),
                r["observed_total"],
                round(r["predicted_total"], 2),
            ]
            for r in report["previous_error_diagnosis"]["by_topic"]
        ],
    )
    body += (
        (
            "<h2>Comparación anual equivalente</h2><p>Selección por valid"
            "ación hasta 2018: <strong>"
        )
        + f["selected_by_development"]
        + (
            "</strong>. Los años posteriores no intervienen en la selecci"
            "ón. El dashboard previo no se reemplaza automáticamente.</p>"
        )
    )
    body += table(
        [
            "Candidato",
            "MAE validación",
            "RMSE validación",
            "MAE diagnóstico observado",
            "RMSE diagnóstico observado",
        ],
        [
            [
                e["config"]["id"],
                round(e["validation"]["mae"], 4),
                round(e["validation"]["rmse"], 4),
                round(e["previously_observed_diagnostic"]["mae"], 4),
                round(e["previously_observed_diagnostic"]["rmse"], 4),
            ]
            for e in f["candidates"]
        ],
    )
    body += "<h3>Validación temporal anidada en desarrollo</h3>" + table(
        ["Año externo", "Años para selección", "Candidato", "MAE externo"],
        [
            [
                r["outer_year"],
                r["selection_years"],
                r["candidate_id"],
                round(r["mae"], 4),
            ]
            for r in f["nested_development"]
        ],
    )
    body += (
        "<h2>2. Temas aprendidos</h2><p>Se usan textos hasta 2015 par"
        "a ajuste y 2016–2018 para comparar. Los textos 2019–2021 no "
        "se utilizaron en esta comparación. Clasificación supervisada"
        " y revisión humana siguen pendientes.</p>"
    )
    body += table(
        [
            "Candidato",
            "NPMI entrenamiento",
            "NPMI validación",
            "Diversidad validación",
            "Cobertura",
            "Dominancia menor a 0,5",
        ],
        [
            [
                c["candidate_id"],
                round(c["training"]["mean_npmi"], 4),
                round(c["validation"]["mean_npmi"], 4),
                round(c["validation"]["term_diversity"], 4),
                round(c["validation"]["coverage"], 4),
                round(c["validation"]["low_dominance_fraction"] or 0, 4),
            ]
            for c in t["candidates"]
        ],
    )
    body += (
        "<p>Candidato para revisión según NPMI de validación: <strong>"
        + t["selected_for_review_by_validation"]
        + (
            "</strong>. Los indicadores no sustituyen una evaluación semá"
            "ntica humana. Los catálogos privados incluyen documentos rea"
            "les y casillas de revisión sin rellenar.</p>"
        )
    )
    for c in t["candidates"]:
        body += (
            "<details><summary>"
            + html.escape(c["candidate_id"])
            + ": términos por tema</summary>"
            + table(
                ["Tema", "Términos", "NPMI de entrenamiento"],
                [
                    [p["topic_id"], ", ".join(p["terms"]), round(p["npmi"], 4)]
                    for p in c["training"]["topics"]
                ],
            )
            + "</details>"
        )
    body += "<h2>3. Auditoría y decisiones pendientes</h2>" + table(
        ["Indicador", "Valor"],
        [
            ["Artículos", a["articles"]],
            ["DOI repetidos: grupos", a["doi_repeated_groups"]],
            ["DOI con años distintos: grupos", a["doi_cross_year_groups"]],
            ["Fechas con día 1", a["day_one"]],
            ["Fechas con 1 de enero", a["january_one"]],
            [
                "Grupos de texto exacto normalizado repetido",
                a["exact_normalized_text_groups"],
            ],
            [
                "Artículos del estudio afectados al excluir DOI/años conflictivos",
                a["quarantine_sensitivity"]["affected_prepared_documents"],
            ],
        ],
    )
    body += (
        "<p>Las fechas originales se conservan. La exclusión de regis"
        "tros conflictivos se calcula solo como sensibilidad sobre re"
        "gistros reales. No se corrigieron años por inferencia ni se "
        "aplicaron decisiones del propietario sin recibirlas.</p>"
    )
    body += table(
        [
            "Relación",
            "Filas originales",
            "Huérfanas",
            "Repetidas válidas",
            "Válidas distintas",
        ],
        [
            [
                k,
                v["raw"],
                v["orphan_rows"],
                v["repeated_valid_pairs"],
                v["valid_distinct"],
            ]
            for k, v in a["relationships"].items()
        ],
    )
    body += "<h2>Trazabilidad con el plan y Azure</h2>" + table(
        ["Código", "ID", "Revisión leída", "Estado leído", "Título"],
        [
            [r["code"], r["id"], r["revision_read"], r["state_read"], r["title"]]
            for r in report["traceability"]["items"]
            if r["type"] == "Requirement"
        ],
    )
    body += (
        "<p>Los CSV, bases originales y resultados anteriores mantien"
        "en sus hashes. El manifiesto identifica protocolo, software,"
        " datos y criterios remotos. El corpus completo, textos, IDs "
        "y casos privados no se adjuntan al informe agregado. PDF, La"
        "kehouse, evaluación humana y confirmación final con datos nu"
        "evos siguen pendientes.</p>"
    )
    return (
        '<meta charset="utf-8"><title>Revisión de prioridades Centine'
        "la</title><style>body{font:16px system-ui;max-width:1200px;m"
        "argin:35px auto;padding:20px;color:#20354a;line-height:1.5}t"
        "able{width:100%;border-collapse:collapse;margin:20px 0}th,td"
        "{padding:9px;border:1px solid #bdcbd9;text-align:left;vertic"
        "al-align:top}th{background:#e1edf5}details{margin:12px 0}h2{"
        "margin-top:36px}</style>"
    ) + body


def run_review(
    corpus,
    study_directory,
    source_directory,
    plan,
    azure_snapshot,
    backlog,
    protocol_file,
    output,
):
    corpus, study_directory, source_directory, output = map(
        lambda p: Path(p).resolve(), (corpus, study_directory, source_directory, output)
    )
    protocol = read_json_file(protocol_file)
    if protocol.get("prior_test_exposure") != "previously_observed_exploratory_only":
        raise AnalyticsError(
            "test_exposure_required", "Previously observed test must be declared"
        )
    if protocol.get("forecast_candidates") != candidates() or protocol.get(
        "topic_candidates"
    ) != [
        "nmf_raw_k6",
        "nmf_raw_k8",
        "nmf_raw_k10",
        "nmf_html_text_k8",
        "lda_html_text_k8",
    ]:
        raise AnalyticsError(
            "protocol_candidate_mismatch",
            "Freeze actual candidate list before execution",
        )
    contract = trace_contract(
        read_json_file(azure_snapshot), read_json_file(backlog), plan
    )
    repository = Path(__file__).resolve().parents[1]
    if (
        output.exists()
        or output.is_relative_to(repository)
        or output.is_relative_to(source_directory)
        or corpus.is_relative_to(output)
        or study_directory.is_relative_to(output)
    ):
        raise AnalyticsError(
            "unsafe_review_output", "Choose new external output outside inputs"
        )
    old = read_json_file(study_directory / "report.json")
    expected = old.pop("report_sha256")
    if fingerprint(old) != expected:
        raise AnalyticsError("study_integrity", "Previous study content changed")
    old["report_sha256"] = expected
    if sha256_file(corpus) != old["identity"]["source_snapshot_sha256"]:
        raise AnalyticsError(
            "corpus_identity_mismatch", "Must use exact previous snapshot"
        )
    with read_database(corpus) as db:
        origin = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
    before = {
        name: sha256_file(source_directory / name) for name in origin["source_sha256"]
    }
    if before != origin["source_sha256"]:
        raise AnalyticsError(
            "raw_source_changed", "CSV hashes differ from ingested snapshot"
        )
    protected = {
        str(corpus): sha256_file(corpus),
        **{str(p): sha256_file(p) for p in study_directory.iterdir() if p.is_file()},
    }
    software = source_files()
    identity = {
        "protocol": protocol,
        "protocol_sha256": sha256_file(Path(protocol_file)),
        "source_sha256": before,
        "previous_run_id": old["run_id"],
        "previous_report_sha256": sha256_file(study_directory / "report.json"),
        "azure_snapshot_sha256": sha256_file(Path(azure_snapshot)),
        "plan_sha256": contract["plan_sha256"],
        "software_sha256": software,
        "versions": {
            n: importlib.metadata.version(n) for n in ("scikit-learn", "numpy", "scipy")
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "protocol.json", protocol)
    _write(output / "traceability.json", contract)
    print(canonical_json({"stage": "diagnose_and_compare_forecasts"}), flush=True)
    old_records = [
        {k: v for k, v in r.items() if k not in ("explanation",)}
        for r in old["prediction"]["test_records"]
    ]
    diagnosis = error_breakdown(old_records)
    forecast, fitted = compare_annual(old["series"], old["protocol"])
    _write(output / "forecast-models.json", fitted)
    print(canonical_json({"stage": "audit_actual_source_and_reconcile"}), flush=True)
    audit, private_cases = audit_snapshot(corpus, study_directory / "prepared.sqlite")
    _write(output / "private-audit-cases.json", private_cases)
    with (output / "owner-decisions.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "kind",
                "doi",
                "article_ids",
                "status",
                "decision",
                "authority",
                "evidence_reference",
            ],
        )
        writer.writeheader()
        for c in private_cases["doi_cases"]:
            writer.writerow(
                {
                    "case_id": c["case_id"],
                    "kind": c["kind"],
                    "doi": c["doi"],
                    "article_ids": "|".join(r["article_id"] for r in c["records"]),
                    "status": "pending_owner_review",
                }
            )
    print(canonical_json({"stage": "fit_and_compare_topics_on_real_texts"}), flush=True)
    topics, catalog = compare_topics(
        corpus,
        study_directory / "prepared.sqlite",
        study_directory / "models.sqlite",
        output,
        old["protocol"],
        software,
    )
    _write(output / "private-topic-catalog.json", catalog)
    with (output / "human-topic-review.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        fields = [
            "candidate_id",
            "model_id",
            "topic_id",
            "terms",
            "article_id",
            "year",
            "title",
            "excerpt",
            "human_label",
            "human_review_status",
            "reviewer",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for t in catalog:
            for doc in t["representatives"]:
                writer.writerow(
                    {
                        **{k: t[k] for k in ("candidate_id", "model_id", "topic_id")},
                        "terms": "|".join(t["terms"]),
                        **{
                            k: doc[k]
                            for k in ("article_id", "year", "title", "excerpt")
                        },
                        "human_review_status": "pending",
                    }
                )
    if not all(
        sha256_file(Path(p)) == digest for p, digest in protected.items()
    ) or before != {n: sha256_file(source_directory / n) for n in before}:
        raise AnalyticsError("input_changed", "Immutable input changed during review")
    report = {
        "run_id": fingerprint(identity),
        "executed_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "traceability": contract,
        "status": "completed_exploratory_review",
        "data_kind": "empirical",
        "previous_error_diagnosis": diagnosis,
        "forecast": forecast,
        "topics": topics,
        "audit": audit,
        "inputs_unchanged": True,
        "pending_owner_review": True,
        "pending_human_topic_review": True,
        "scientific_scope": (
            "Exploratory development; no newly untouched final test or hu"
            "man evaluation claimed"
        ),
    }
    report["report_sha256"] = fingerprint(report)
    _write(output / "report.json", report)
    with sqlite3.connect(output / "review.sqlite") as db:
        db.execute("CREATE TABLE review (id TEXT PRIMARY KEY,payload TEXT)")
        db.execute(
            "INSERT INTO review VALUES (?,?)",
            (report["run_id"], canonical_json(report)),
        )
    public = {k: v for k, v in report.items() if k not in ("identity", "report_sha256")}
    _write(output / "public-results.json", public)
    (output / "review.html").write_text(render_report(public), encoding="utf-8")
    with zipfile.ZipFile(
        output / "executed-source.zip", "w", zipfile.ZIP_DEFLATED
    ) as z:
        for relative, digest in software.items():
            p = repository / relative
            if sha256_file(p) != digest:
                raise AnalyticsError(
                    "software_changed", "Software changed during execution"
                )
            z.write(p, relative)
    _write(
        output / "manifest.json",
        {
            p.name: sha256_file(p)
            for p in output.iterdir()
            if p.is_file() and p.name != "manifest.json"
        },
    )
    print(
        canonical_json(
            {
                "stage": "complete",
                "run_id": report["run_id"],
                "forecast_selected": forecast["selected_by_development"],
                "topic_selected": topics["selected_for_review_by_validation"],
            }
        ),
        flush=True,
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "corpus",
        "study-directory",
        "source-directory",
        "plan",
        "azure-snapshot",
        "backlog",
        "protocol",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run_review(
            args.corpus,
            args.study_directory,
            args.source_directory,
            args.plan,
            args.azure_snapshot,
            args.backlog,
            args.protocol,
            args.output,
        )
        return 0
    except (AnalyticsError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_review"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
