# tender/services/abcp_step1.py

import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from django.conf import settings
from dotenv import load_dotenv

from ..models import TenderJob

logger = logging.getLogger(__name__)

# Загружаем .env один раз при импорте модуля
load_dotenv()

ABCP_HOST = os.getenv("ABCP_HOST", "").rstrip("/")
ABCP_USERLOGIN = os.getenv("ABCP_USERLOGIN", "")
ABCP_USERPSW = os.getenv("ABCP_USERPSW", "")


def _append_log(job: TenderJob, message: str) -> None:
    """
    Удобный помощник: пишет в logger + дописывает в job.log.
    """
    logger.info(message)
    job.log = (job.log or "") + message + "\n"
    job.save(update_fields=["log"])


def _ensure_env(job: TenderJob) -> bool:
    """
    Проверяем, что заполнены переменные окружения для ABCP.
    Если чего-то нет — пишем в лог job и возвращаем False.
    """
    missing = []
    if not ABCP_HOST:
        missing.append("ABCP_HOST")
    if not ABCP_USERLOGIN:
        missing.append("ABCP_USERLOGIN")
    if not ABCP_USERPSW:
        missing.append("ABCP_USERPSW")

    if missing:
        _append_log(
            job,
            f"Ошибка конфигурации: отсутствуют переменные окружения: {', '.join(missing)}",
        )
        job.status = TenderJob.STATUS_ERROR
        job.save(update_fields=["status"])
        return False

    return True


def _build_result_path(job: TenderJob) -> Path:
    """
    Формируем путь для результирующего XLSX-файла.
    Например: MEDIA_ROOT/tender_results/job_1_result.xlsx
    """
    media_root = Path(settings.MEDIA_ROOT)
    out_dir = media_root / "tender_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"job_{job.id}_abcp_result.xlsx"
    return out_dir / filename


def run_abcp_pricing(job: TenderJob) -> Optional[Path]:
    """
    Главная функция этапа 1: берёт job, запускает проценку через ABCP API
    и возвращает путь к созданному XLSX либо None в случае ошибки.

    Внутрь этой функции мы встроим твой текущий скрипт API_v2,
    адаптировав его под Django.
    """
    # 1. Базовая проверка конфигурации
    if not _ensure_env(job):
        return None

    if not job.input_file:
        _append_log(job, "Ошибка: у задачи нет прикреплённого входного файла.")
        job.status = TenderJob.STATUS_ERROR
        job.save(update_fields=["status"])
        return None

    input_path = Path(job.input_file.path)
    if not input_path.exists():
        _append_log(job, f"Ошибка: входной файл не найден: {input_path}")
        job.status = TenderJob.STATUS_ERROR
        job.save(update_fields=["status"])
        return None

    profile_id = job.client_profile.profile_id
    _append_log(job, f"Старт проценки по API ABCP для profileId={profile_id}")
    _append_log(job, f"Входной файл: {input_path}")

    # 2. Путь для результата
    result_path = _build_result_path(job)

    # 3. Здесь НУЖНО перенести твой код из API_v2.py
    #    Основная идея:
    #      - читаем input_path через pandas
    #      - проверяем наличие колонок brand / sku / qty
    #      - делаем уникальные запросы (brand, sku, qty)
    #      - для каждого запроса вызываем ABCP /search/articles/
    #      - парсим JSON и собираем DataFrame по структуре, как раньше
    #      - сохраняем result_path в Excel с листами Data и Errors
    #
    # Ниже — ЗАГЛУШКА, чтобы код не падал.
    # Вместо неё ты вставишь свою реальную логику.

    try:
        # Пример чтения файла и проверки колонок
        df = pd.read_excel(input_path)
        required_cols = {"brand", "sku", "qty"}
        if not required_cols.issubset(df.columns.str.lower()):
            _append_log(
                job,
                f"Заглушка: не найдены все обязательные колонки {required_cols} "
                f"в файле {input_path.name}. Реальная логика ещё не перенесена.",
            )
            # Пишем пустой файл, чтобы ссылка result_file всё же была
            empty = pd.DataFrame({"message": ["Проценка ещё не реализована (заглушка)."]})
            with pd.ExcelWriter(result_path, engine="openpyxl") as writer:
                empty.to_excel(writer, sheet_name="Info", index=False)

        # В РЕАЛЬНОЙ версии здесь будет:
        # from .your_old_module import process_file
        # process_file(input_path, profile_id, result_path, job_logger=_append_log)

    except Exception as exc:  # noqa: BLE001
        _append_log(job, f"Исключение при выполнении проценки: {exc!r}")
        job.status = TenderJob.STATUS_ERROR
        job.save(update_fields=["status"])
        return None

    # 4. Если дошли сюда — считаем, что всё ок
    rel_path = result_path.relative_to(settings.MEDIA_ROOT)
    job.result_file.name = str(rel_path).replace("\\", "/")
    job.status = TenderJob.STATUS_DONE
    job.save(update_fields=["result_file", "status"])

    _append_log(job, f"Проценка завершена, результат: {result_path}")
    return result_path
