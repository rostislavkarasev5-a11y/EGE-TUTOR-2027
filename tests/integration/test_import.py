"""Импорт задач: проверка, дубли, отчёт, запись пачкой и отмена (ADR-0007, ADR-0011)."""

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import (
    AnswerType,
    ImportBatchStatus,
    Subject,
    TaskSource,
    VerificationStatus,
)
from tests.conftest import REPO_ROOT

GOOD_YAML = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "Тестовый конспект"
tasks:
  - exam_item: 6
    statement: "Решите уравнение x + 1 = 3."
    answer: 2
    skills: [M06.algebraic]
  - exam_item: 13
    statement: "Решите уравнение и отберите корни."
    skills: [M13.trig_equations]
"""


def _messages(issues):
    return [(i.row, i.message) for i in issues]


def _errors_of(report, row):
    return [m for r, m in _messages(report.errors) if r == row]


def _one_task(**fields) -> str:
    base = {
        "subject": "math",
        "exam_item": 6,
        "statement": "Решите уравнение 5x = 10.",
        "answer": "2",
        "source": "USER_MATERIAL",
        "source_ref": "конспект",
        "skills": "[M06.algebraic]",
    }
    base.update(fields)
    lines = [f"    {k}: {v}" for k, v in base.items() if v is not None]
    lines[0] = "  - " + lines[0].lstrip()
    return "tasks:\n" + "\n".join(lines) + "\n"


def test_preview_does_not_write(tutor, write_file):
    report = tutor.preview_import(write_file("t.yaml", GOOD_YAML))
    assert report.errors == []
    assert len(report.accepted) == 2
    assert tutor.tasks() == []


def test_defaults_and_answer_type_from_spec(tutor, write_file):
    report = tutor.preview_import(write_file("t.yaml", GOOD_YAML))
    short, extended = report.accepted
    assert short.subject == Subject.MATH_PROFILE
    assert short.answer_type == AnswerType.NUMBER
    assert short.verification_status == VerificationStatus.UNVERIFIED
    assert extended.answer_type == AnswerType.EXTENDED
    assert extended.answer is None


def test_apply_writes_batch_and_tasks(tutor, write_file, fixed_clock):
    result = tutor.import_tasks(write_file("t.yaml", GOOD_YAML))
    assert result.batch is not None
    assert result.batch.added_count == 2
    assert result.batch.created_at == fixed_clock.now()
    tasks = tutor.tasks()
    assert len(tasks) == 2
    assert {t.import_batch_id for t in tasks} == {result.batch.id}
    assert tasks[0].skills == ("M06.algebraic",)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"subject": "physics"}, "subject"),
        ({"exam_item": 42}, "нет задания №42"),
        ({"statement": '"   "'}, "пустое условие"),
        ({"source": None}, "source: не указан"),
        ({"source": "BOOK"}, "source: неизвестное значение"),
        ({"source_ref": None}, "source_ref"),
        ({"answer": None}, "нужен ответ"),
        ({"answer": "два"}, "не число"),
        ({"answer_type": "EXTENDED"}, "не подходит"),
        ({"difficulty": 9}, "difficulty"),
        ({"time_norm_minutes": -1}, "time_norm_minutes"),
        ({"skills": "[M06.nope]"}, "неизвестные коды навыков"),
        ({"verification_status": "AUTO_CHECKED"}, "только UNVERIFIED или REVIEWED"),
        ({"assets": "[missing.txt]"}, "файл не найден"),
    ],
)
def test_invalid_rows_are_reported(tutor, write_file, fields, expected):
    report = tutor.preview_import(write_file("t.yaml", _one_task(**fields)))
    assert report.accepted == []
    assert any(expected in m for m in _errors_of(report, 1)), report.errors


def test_ai_generated_must_stay_unverified(tutor, write_file):
    text = _one_task(source="AI_GENERATED", verification_status="REVIEWED")
    report = tutor.preview_import(write_file("t.yaml", text))
    assert any("от ИИ" in m for m in _errors_of(report, 1))

    ok = tutor.preview_import(write_file("t2.yaml", _one_task(source="AI_GENERATED")))
    assert ok.accepted[0].verification_status == VerificationStatus.UNVERIFIED


def test_ai_generated_task_is_always_labelled(tutor, write_file):
    tutor.import_tasks(write_file("t.yaml", _one_task(source="AI_GENERATED")))
    task = tutor.tasks()[0]
    assert task.source == TaskSource.AI_GENERATED
    assert "не задание ФИПИ" in task.source_label


def test_warnings_do_not_block(tutor, write_file):
    text = _one_task(skills=None, extra_field="x")
    report = tutor.preview_import(write_file("t.yaml", text))
    assert len(report.accepted) == 1
    warnings = " ".join(m for _, m in _messages(report.warnings))
    assert "навыки не указаны" in warnings
    assert "extra_field" in warnings


def test_skill_from_other_exam_item_is_a_warning(tutor, write_file):
    report = tutor.preview_import(write_file("t.yaml", _one_task(skills="[M04.classical]")))
    assert len(report.accepted) == 1
    assert any("обычно не относятся" in m for _, m in _messages(report.warnings))


def test_only_valid_rows_are_written(tutor, write_file):
    text = _one_task() + _one_task(exam_item=99, statement="другая").replace("tasks:\n", "")
    result = tutor.import_tasks(write_file("t.yaml", text))
    assert result.batch.added_count == 1
    assert result.batch.rejected_count == 1
    assert len(tutor.tasks()) == 1


def test_duplicates_in_file_and_in_db(tutor, write_file):
    dup = _one_task(statement='"Решите   уравнение 5X = 10."').replace("tasks:\n", "")
    report = tutor.preview_import(write_file("t.yaml", _one_task() + dup))
    assert any("повторяет задачу №1" in m for m in _errors_of(report, 2))

    tutor.import_tasks(write_file("a.yaml", _one_task()))
    again = tutor.preview_import(write_file("b.yaml", _one_task()))
    assert any("уже есть в базе" in m for m in _errors_of(again, 1))


def test_rollback_hides_tasks_keeps_history_and_allows_reimport(tutor, write_file, fixed_clock):
    path = write_file("t.yaml", GOOD_YAML)
    first = tutor.import_tasks(path).batch
    rolled = tutor.rollback_import(first.id)
    assert rolled.status == ImportBatchStatus.ROLLED_BACK
    assert rolled.rolled_back_at == fixed_clock.now()
    assert tutor.tasks() == []
    assert [b.id for b in tutor.import_batches()] == [first.id]

    second = tutor.import_tasks(path).batch  # после отмены те же задачи можно загрузить заново
    assert second.added_count == 2
    with pytest.raises(AppError, match="уже отменён"):
        tutor.rollback_import(first.id)
    with pytest.raises(AppError, match="не найден"):
        tutor.rollback_import(999)


def test_rolled_back_task_is_not_shown(tutor, write_file):
    batch = tutor.import_tasks(write_file("t.yaml", _one_task())).batch
    task_id = tutor.tasks()[0].id
    tutor.rollback_import(batch.id)
    with pytest.raises(AppError, match="не найдена"):
        tutor.task(task_id)


def test_assets_are_copied_by_hash(tutor, write_file):
    write_file("files/data.txt", "1\n2\n3\n")
    text = _one_task(subject="informatics", exam_item=17, skills="[I17.sequences]")
    text = text.replace("    answer:", "    assets: [files/data.txt]\n    answer:")
    tutor.import_tasks(write_file("t.yaml", text))
    task = tutor.tasks()[0]
    (asset,) = task.assets
    stored = tutor.asset_path(asset)
    assert stored.read_text() == "1\n2\n3\n"
    assert stored.is_relative_to(tutor.settings.data_dir / "private_content")
    assert stored.name == f"{asset.sha256}.txt"


def test_assets_outside_task_folder_are_rejected(tutor, write_file, tmp_path):
    # Файл задач (например, загруженный на сайт) не должен дотягиваться до чужих файлов.
    (tmp_path / "secret.txt").write_text("личное")
    text = _one_task(subject="informatics", exam_item=17, skills="[I17.sequences]")
    text = text.replace("    answer:", "    assets: [../secret.txt]\n    answer:")
    report = tutor.preview_import(write_file("t.yaml", text))
    assert any("рядом с файлом задач" in m for m in _errors_of(report, 1))
    assert report.accepted == []


def test_csv_cp1251_with_semicolons(tutor, write_file):
    text = (
        "subject;exam_item;statement;answer;source;source_ref;skills\r\n"
        "математика;4;Найдите вероятность события.;0,25;USER_MATERIAL;сборник, с. 3;"
        "M04.classical\r\n"
        "informatics;14;Сколько единиц в записи числа 7?;3;user_material;конспект;I14.bases\r\n"
    )
    report = tutor.preview_import(write_file("t.csv", text.encode("cp1251")))
    assert report.errors == []
    assert report.file_format == "csv"
    math, inf = report.accepted
    assert math.answer == "0.25"
    assert inf.subject == Subject.INFORMATICS
    assert inf.source == TaskSource.USER_MATERIAL


def test_csv_utf8_with_bom_and_commas(tutor, write_file):
    text = (
        "subject,exam_item,statement,answer,source,source_ref,skills\n"
        'math,6,"Решите уравнение 2x = 8.",4,USER_MATERIAL,конспект,M06.algebraic\n'
    )
    report = tutor.preview_import(write_file("t.csv", "﻿" + text))
    assert report.errors == []
    assert report.accepted[0].answer == "4"


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("t.txt", "x", "неподдерживаемый формат"),
        ("t.yaml", "tasks: [", "ошибка YAML"),
        ("t.yaml", "items: []", "нужен список tasks"),
        ("t.yaml", "tasks: [1, 2]", "должна быть словарём"),
    ],
)
def test_broken_files_are_reported_as_file_errors(tutor, write_file, name, content, expected):
    report = tutor.preview_import(write_file(name, content))
    assert report.file_error
    assert expected in report.errors[0].message
    assert tutor.import_tasks(write_file(name, content)).batch is None


def test_bundled_templates_and_sample_are_valid(tutor):
    for rel in (
        "content/templates/tasks_template.yaml",
        "content/templates/tasks_template.csv",
        "content/sample/tasks.yaml",
    ):
        report = tutor.preview_import(REPO_ROOT / rel)
        assert report.errors == [], (rel, report.errors)
        assert report.accepted, rel


def test_sample_tasks_are_all_ai_generated(tutor):
    report = tutor.preview_import(REPO_ROOT / "content/sample/tasks.yaml")
    assert {d.source for d in report.accepted} == {TaskSource.AI_GENERATED}
    assert {d.verification_status for d in report.accepted} == {VerificationStatus.UNVERIFIED}
