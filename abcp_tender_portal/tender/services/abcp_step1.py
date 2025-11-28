# tender/services/abcp_step1.py

import logging
import os
from pathlib import Path
from typing import Optional
import shutil

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


def run_abcp_pricing(job: TenderJob) -> None:
    """
    Заглушка «проценки» по API ABCP.

    Сейчас она просто копирует входной XLSX-файл в media/tender_results/
    и прописывает путь в job.result_file.

    Позже сюда можно будет подставить реальный код проценки.
    """
    media_root = Path(settings.MEDIA_ROOT)
    input_path = Path(job.input_file.path)

    # Каталог для результатов
    result_dir = media_root / "tender_results"
    result_dir.mkdir(parents=True, exist_ok=True)

    # Имя выходного файла
    result_path = result_dir / f"job_{job.id}_abcp_result.xlsx"

    logger.info(
        "Старт проценки по API ABCP для profileId=%s\nВходной файл: %s",
        job.client_profile.profile_id,
        input_path,
    )

    try:
        # ----- заглушка: просто копируем входной файл -----
        shutil.copy2(input_path, result_path)

        # относительный путь от MEDIA_ROOT -> в FileField нужно именно его
        rel_path = os.path.relpath(result_path, media_root)
        # Django сам склеит MEDIA_ROOT + name
        job.result_file.name = rel_path.replace("\\", "/")

        job.status = TenderJob.STATUS_DONE
        job.log = (job.log or "") + f"\nOK: файл результата сохранён в {result_path}"
        logger.info("Проценка завершена, результат: %s", result_path)

    except Exception as exc:
        msg = f"Ошибка во время проценки: {exc!r}"
        job.status = TenderJob.STATUS_ERROR
        job.log = (job.log or "") + "\n" + msg
        logger.exception(msg)

    finally:
        job.save(update_fields=["status", "log", "result_file"])
