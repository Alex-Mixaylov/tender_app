# tender/services/abcp_step1.py

import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import pandas as pd
import requests
from django.conf import settings
from dotenv import load_dotenv

from ..models import TenderJob

logger = logging.getLogger(__name__)

# ----------------------- Загрузка .env и конфиг -----------------------

# Явно грузим .env из BASE_DIR
load_dotenv(os.path.join(settings.BASE_DIR, ".env"))

_raw_host = os.getenv("ABCP_HOST", "").strip()
# подстрахуемся: если забыли схему — считаем, что https
if _raw_host and not _raw_host.startswith(("http://", "https://")):
    _raw_host = "https://" + _raw_host

ABCP_HOST = _raw_host.rstrip("/")
ABCP_USERLOGIN = os.getenv("ABCP_USERLOGIN", "")
# В ABCP обычно ожидается md5 пароля; считаем, что в .env уже лежит нужное значение
ABCP_USERPSW = os.getenv("ABCP_USERPSW", "")


def _append_log(job: TenderJob, message: str) -> None:
    """
    Пишет сообщение в logger и в job.log + сохраняет задачу.
    Сохраняем все поля job (без update_fields), чтобы обновления статуса/файла
    точно попали в БД.
    """
    logger.info(message)
    job.log = (job.log or "") + message + "\n"
    job.save()


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
        job.status = TenderJob.STATUS_ERROR
        _append_log(
            job,
            "Ошибка конфигурации ABCP: отсутствуют переменные окружения: "
            + ", ".join(missing),
        )
        return False

    return True


# ----------------------- Вспомогательные функции API -----------------------


def detect_columns(df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
    """
    Автоматически определяет колонки:
      - бренд
      - артикул
      - количество (qty) — опционально
    """
    lower_cols = {col: str(col).lower().strip() for col in df.columns}

    brand_col = next(
        (
            col
            for col, lc in lower_cols.items()
            if any(k in lc for k in ["бренд", "brand", "производитель"])
        ),
        None,
    )
    article_col = next(
        (
            col
            for col, lc in lower_cols.items()
            if any(k in lc for k in ["артикул", "article", "код", "номер", "sku"])
        ),
        None,
    )

    qty_col = next(
        (
            col
            for col, lc in lower_cols.items()
            if any(k in lc for k in ["qty", "кол-во", "количество", "quantity"])
        ),
        None,
    )

    if not brand_col or not article_col:
        raise RuntimeError("Не удалось определить колонки для бренда и артикула")

    logger.info(
        "Колонка бренда: '%s', колонка артикула: '%s', колонка qty: '%s'",
        brand_col,
        article_col,
        qty_col,
    )

    return brand_col, article_col, qty_col


def build_search_params(
    login: str,
    psw: str,
    brand: str,
    article: str,
    profile_id: str,
) -> Dict[str, str]:
    """Формирует параметры запроса к API search/articles."""
    params = {
        "userlogin": login,
        "userpsw": psw,
        "number": article,
        "brand": brand,
        "disableFiltering": "1",
        "withOutAnalogs": "0",
        "useOnlineStocks": "1",
    }
    if profile_id:
        params["profileId"] = profile_id
    return params


def extract_stock_name(item: dict) -> str:
    """
    Пытается вытащить название/идентификатор склада из ответа по позиции.

    По данным техподдержки ABCP, название склада — это название маршрута
    поставщика в поле supplierDescription. Оно может содержать HTML-теги,
    поэтому мы их вычищаем.
    """
    raw = (
        item.get("officeName")
        or item.get("stockName")
        or item.get("warehouseName")
        or item.get("storageName")
        or item.get("deliveryOffice")
        or item.get("supplierDescription")  # главное поле
    )

    if not raw:
        logger.debug(
            "Склад НЕ найден в позиции %s %s. Ключи: %s",
            item.get("brand"),
            item.get("number"),
            list(item.keys()),
        )
        return ""

    # Убираем HTML-разметку типа <span>...</span><br> и лишние пробелы
    cleaned = re.sub(r"<[^>]+>", " ", str(raw))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    logger.debug(
        "Склад найден для %s %s: %s",
        item.get("brand"),
        item.get("number"),
        cleaned,
    )
    return cleaned


def extract_deadline_text(item: dict) -> str:
    """
    Возвращает человекочитаемый срок поставки по позиции.

    Логика:
    - если есть непустой deadlineReplace — используем его;
    - иначе считаем, что это режим «на складе».
    """
    raw = item.get("deadlineReplace")
    if raw:
        cleaned = re.sub(r"<[^>]+>", " ", str(raw))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            return cleaned

    return "на складе"


def extract_supplier_name(item: dict) -> str:
    """
    Возвращает код/ID поставщика для колонки 'Поставщик'.

    Сейчас используем:
    - distributorCode, если он задан (можно настроить в АВСР
      как человекочитаемый код/имя);
    - иначе подставляем distributorId как строку.
    """
    name = item.get("distributorCode")
    if name:
        return str(name)

    dist_id = item.get("distributorId")
    if dist_id is not None:
        return str(dist_id)

    return ""


def extract_supplier_full_name(item: dict, distributors_map: Dict[int, str]) -> str:
    """
    Возвращает полное название поставщика (для колонки 'Название поставщика')
    по distributorId через заранее загруженный словарь cp/distributors.
    """
    dist_id = item.get("distributorId")
    if dist_id is None:
        return ""

    try:
        return distributors_map.get(int(dist_id), "") or ""
    except Exception:
        return ""


def load_distributors_map() -> Dict[int, str]:
    """
    Загружает список поставщиков через cp/distributors
    и возвращает словарь {id: человекочитаемое_название}.
    Берём publicName, если он есть, иначе name.
    """
    if not ABCP_HOST or not ABCP_USERLOGIN or not ABCP_USERPSW:
        logger.warning(
            "Невозможно загрузить cp/distributors: не заданы ABCP_HOST/USERLOGIN/USERPSW"
        )
        return {}

    url = ABCP_HOST.rstrip("/") + "/cp/distributors"
    params = {
        "userlogin": ABCP_USERLOGIN,
        "userpsw": ABCP_USERPSW,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        if not isinstance(data, list):
            logger.warning("Неожиданный формат ответа cp/distributors: %s", type(data))
            return {}

        result: Dict[int, str] = {}
        for row in data:
            try:
                dist_id = row.get("id")
                if dist_id is None:
                    continue

                name = row.get("publicName") or row.get("name") or str(dist_id)
                result[int(dist_id)] = str(name)
            except Exception:
                # не валим весь список из-за одной кривой записи
                continue

        logger.info("Загружено поставщиков из cp/distributors: %s", len(result))
        return result

    except Exception as exc:
        logger.error("Ошибка при запросе cp/distributors: %r", exc)
        return {}


def call_search_articles(
    host: str,
    login: str,
    psw: str,
    brand: str,
    article: str,
    profile_id: str,
) -> List[dict]:
    """
    Запрос к API ABCP search/articles.
    Возвращает список позиций (list[dict]) или [] в случае ошибки/пустого ответа.
    """
    url = host.rstrip("/") + "/search/articles/"
    params = build_search_params(login, psw, brand, article, profile_id)

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "errorCode" in data:
            logger.warning("API ошибка %s для %s %s", data, brand, article)
            return []
        if isinstance(data, list):
            return data
        logger.warning(
            "Неожиданный формат ответа API для %s %s: %s",
            brand,
            article,
            type(data),
        )
        return []
    except Exception as e:
        logger.error("Ошибка при запросе %s %s: %s", url, params, e)
        return []


def normalize_article(s: str) -> str:
    """Нормализация артикула/бренда: upper, без пробелов, тире, точек и слэшей."""
    s = str(s or "").upper()
    return re.sub(r"[\s\-./]", "", s)

def format_profile_name(raw: str) -> str:
    """
    Обрезает хвост в последних скобках.
    Пример:
      'CPZ-2322 / Агропоставка МТ Мираторг (CPZ2322@CPZ2322.ru)'
      -> 'CPZ-2322 / Агропоставка МТ Мираторг'
    """
    if not raw:
        return ""
    text = str(raw).strip()
    # убираем последнее " ( ... )" в конце строки
    cleaned = re.sub(r"\s*\([^()]*\)\s*$", "", text).strip()
    return cleaned or text



def extract_row_from_item(
    item: dict,
    profile_id: str,
    rq_brand: str,
    rq_article: str,
    rq_qty,
    distributors_map: Dict[int, str],
) -> Dict[str, str]:
    """Формирует строку для листа Data."""
    stock_name = extract_stock_name(item)
    deadline_text = extract_deadline_text(item)
    supplier_name = extract_supplier_name(item)
    supplier_full_name = extract_supplier_full_name(item, distributors_map)

    return {
        "Запрашиваемый бренд": rq_brand,
        "Запрашиваемый артикул": rq_article,
        "Бренд": item.get("brand") or item.get("brandFix") or rq_brand,
        "Артикул": item.get("number") or item.get("numberFix") or rq_article,
        "Описание": item.get("description") or "",
        "Запрашиваемое кол-во": rq_qty if rq_qty is not None else "",
        "Наличие": (
            item.get("availability")
            or item.get("rest")
            or item.get("qty")
            or ""
        ),
        "Расчет по профилю клиента": profile_id,
        "Поставщик": supplier_name,              # код/ID поставщика
        "Склад": stock_name,
        "Название поставщика": supplier_full_name,  # полное имя из cp/distributors
        "Срок": deadline_text,
        "Цена по профилю": (
            item.get("price")
            or item.get("priceOut")
            or item.get("priceInSiteCurrency")
            or ""
        ),
    }


# ----------------------------- Основная логика -----------------------------


def run_abcp_pricing(job: TenderJob) -> None:
    """
    Основная функция Этапа 1.

    Что делает:
      1. Проверяет .env (ABCP_HOST, ABCP_USERLOGIN, ABCP_USERPSW).
      2. Читает входной XLSX из job.input_file.
      3. Определяет колонки бренд / артикул / qty.
      4. Загружает список поставщиков (cp/distributors).
      5. Формирует уникальные пары (brand, article, qty) и по каждой
         вызывает ABCP /search/articles/.
      6. Собирает результаты в два DataFrame:
         - Data (предложения)
         - Errors (по каким запросам ничего не найдено / ошибка API).
      7. Сохраняет результат в Excel:
         MEDIA_ROOT / "tenders/output/abcp_tender_search_job_<id>.xlsx"
         (листы Data и Errors).
      8. Обновляет job.result_file, job.status и job.log.
    """
    _append_log(
        job,
        f"Старт проценки ABCP для задачи #{job.id} "
        f"(profileId={job.client_profile.profile_id})",
    )

    # 1. Проверка .env
    if not _ensure_env(job):
        return

    # 2. Читаем входной XLSX
    try:
        input_path = Path(job.input_file.path)
    except Exception as exc:
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка: не удалось получить путь к входному файлу: {exc!r}")
        return

    if not input_path.exists():
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка: входной файл не найден: {input_path}")
        return

    try:
        df_in = pd.read_excel(input_path)
    except Exception as exc:
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка чтения XLSX '{input_path}': {exc!r}")
        return

    if df_in.empty:
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка: входной файл '{input_path}' пустой.")
        return

    # 3. Определяем колонки
    try:
        brand_col, article_col, qty_col = detect_columns(df_in)
    except Exception as exc:
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка определения колонок бренда/артикула: {exc}")
        return

    profile_id = job.client_profile.profile_id
    profile_label = format_profile_name(job.client_profile.name or "")


    # 3.5. Загружаем список поставщиков один раз для задачи
    distributors_map: Dict[int, str] = load_distributors_map()
    if distributors_map:
        _append_log(job, f"Загружено поставщиков из ABCP: {len(distributors_map)}")
    else:
        _append_log(
            job,
            "Не удалось получить список поставщиков через cp/distributors "
            "или список пустой. Колонка 'Название поставщика' может быть пустой.",
        )

    # 4. Формируем уникальные пары (brand, article, qty)
    if qty_col:
        df_pairs = df_in[[brand_col, article_col, qty_col]].dropna(
            subset=[brand_col, article_col]
        )
    else:
        df_pairs = df_in[[brand_col, article_col]].dropna(
            subset=[brand_col, article_col]
        )
        df_pairs["__qty"] = None
        qty_col = "__qty"

    df_pairs = df_pairs.drop_duplicates()
    pairs = df_pairs.to_dict("records")
    total_pairs = len(pairs)

    _append_log(
        job,
        f"Найдено уникальных запросов (бренд+артикул+qty): {total_pairs}",
    )

    all_rows: List[Dict[str, str]] = []
    errors_rows: List[Dict[str, str]] = []

    # 5. Обход пар и запросы к ABCP
    for i, rec in enumerate(pairs, start=1):
        brand = str(rec[brand_col]).strip()
        article = str(rec[article_col]).strip()
        rq_qty = rec.get(qty_col)

        logger.info("=== ABCP поиск %s/%s: %s %s ===", i, total_pairs, brand, article)

        items = call_search_articles(
            ABCP_HOST,
            ABCP_USERLOGIN,
            ABCP_USERPSW,
            brand,
            article,
            profile_id,
        )

        if not items:
            logger.warning(
                "Для %s %s не получено ни одного предложения "
                "(возможен 404 или пустой ответ API).",
                brand,
                article,
            )
            errors_rows.append(
                {
                    "Запрашиваемый бренд": brand,
                    "Запрашиваемый артикул": article,
                    "Запрашиваемое кол-во": rq_qty
                    if rq_qty is not None
                    else "",
                    "Комментарий": "Нет предложений или ошибка API",
                }
            )
            continue

        for item in items:
            row = extract_row_from_item(
                item,
                profile_label,
                brand,
                article,
                rq_qty,
                distributors_map,
            )
            all_rows.append(row)

        # Каждые 20 запросов пишем прогресс в лог задачи
        if i % 20 == 0 or i == total_pairs:
            _append_log(job, f"Обработано {i} из {total_pairs} запросов...")

    # 6. Формируем DataFrame для листа Data
    data_columns = [
        "Запрашиваемый бренд",
        "Запрашиваемый артикул",
        "Группа результата",
        "Бренд",
        "Артикул",
        "Описание",
        "Запрашиваемое кол-во",
        "Наличие",
        "Расчет по профилю клиента",
        "Поставщик",
        "Склад",
        "Название поставщика",
        "Срок",
        "Расчет по профилю клиента",
    ]

    if all_rows:
        df_data = pd.DataFrame(all_rows)

        # Добавляем колонку "Группа результата"
        df_data["_is_exact"] = df_data.apply(
            lambda r: (
                normalize_article(r["Бренд"])
                == normalize_article(r["Запрашиваемый бренд"])
                and normalize_article(r["Артикул"])
                == normalize_article(r["Запрашиваемый артикул"])
            ),
            axis=1,
        )
        df_data["Группа результата"] = df_data["_is_exact"].map(
            {True: "Запрашиваемый артикул", False: "Кросс"}
        )
        df_data.drop(columns=["_is_exact"], inplace=True)

        # Очищаем "Запрашиваемое кол-во" для кроссов
        df_data.loc[
            df_data["Группа результата"] != "Запрашиваемый артикул",
            "Запрашиваемое кол-во",
        ] = ""

        # Переупорядочиваем колонки (в т.ч. "Название поставщика" после "Склад")
        df_data = df_data[
            [
                "Запрашиваемый бренд",
                "Запрашиваемый артикул",
                "Группа результата",
                "Бренд",
                "Артикул",
                "Описание",
                "Запрашиваемое кол-во",
                "Наличие",
                "Цена по профилю",
                "Срок",
                "Склад",
                "Поставщик",
                "Название поставщика",
                "Расчет по профилю клиента",

            ]
        ]

        # Сортировка для удобства
        df_data = df_data.sort_values(
            by=[
                "Запрашиваемый бренд",
                "Запрашиваемый артикул",
                "Группа результата",
                "Бренд",
                "Артикул",
            ],
            ascending=[True, True, True, True, True],
        ).reset_index(drop=True)
    else:
        df_data = pd.DataFrame(columns=data_columns)

    # 7. Формируем DataFrame для листа Errors
    err_columns = [
        "Запрашиваемый бренд",
        "Запрашиваемый артикул",
        "Запрашиваемое кол-во",
        "Комментарий",
    ]

    if errors_rows:
        df_errors = pd.DataFrame(errors_rows)[err_columns]
    else:
        df_errors = pd.DataFrame(columns=err_columns)

    # 8. Сохранение в Excel в MEDIA_ROOT/tenders/output/
    media_root = Path(settings.MEDIA_ROOT)
    output_dir = media_root / "tenders" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"abcp_tender_search_job_{job.id}.xlsx"

    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_data.to_excel(writer, sheet_name="Data", index=False)
            df_errors.to_excel(writer, sheet_name="Errors", index=False)

        # относительный путь от MEDIA_ROOT -> FileField хранит именно его
        rel_path = output_path.relative_to(media_root)
        job.result_file.name = str(rel_path).replace("\\", "/")
        job.status = TenderJob.STATUS_DONE

        _append_log(
            job,
            f"OK: файл результата сохранён в {output_path} "
            f"(строк Data: {len(df_data)}, Errors: {len(df_errors)})",
        )
    except Exception as exc:
        job.status = TenderJob.STATUS_ERROR
        _append_log(job, f"Ошибка сохранения файла результата: {exc!r}")
