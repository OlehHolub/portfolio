# bq_guard.py
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional, Tuple, Dict, Union

from google.cloud import bigquery

# Лимиты бесплатного уровня (можно поменять под себя)
QUERY_LIMIT_BYTES = 1 * 1024**4      # 1 TB
STORAGE_LIMIT_BYTES = 10 * 1024**3   # 10 GB

# Какие multi‑region проверять (если работаешь только в EU — оставь ['region-eu'])
DEFAULT_REGIONS = ['region-eu','region-us']


def _region_to_location(region: str) -> str:
    # 'region-eu' -> 'EU', 'region-us' -> 'US', 'EU'/'US' -> как есть
    region = region.strip()
    if region.upper() in ("EU", "US"):
        return region.upper()
    if region.startswith("region-"):
        return region.split("-", 1)[1].upper()
    return region.upper()


def _month_bounds_utc() -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # следующий месяц: 28-е + 4 дня гарантировано перекинет на след. месяц
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def _sum_query_bytes_billed(
    client: bigquery.Client,
    regions: Iterable[str],
    project_id: Optional[str] = None,
) -> int:
    """
    Сумма total_bytes_billed за текущий месяц, точь-в-точь как в твоём проверочном примере:
    берём JOBS_BY_PROJECT → группируем по дням → суммируем billed_bytes в pandas.
    Фильтр по project_id убран (как в твоём SQL), чтобы исключить влияние прав/особенностей вью.
    """
    total = 0
    for region in regions:
        location = _region_to_location(region)  # 'region-us' -> 'US'
        sql = f"""
        SELECT
          DATE(creation_time) AS day,
          SUM(total_bytes_billed) AS billed_bytes
        FROM `{region}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
        WHERE
          creation_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
          AND job_type = 'QUERY'
        GROUP BY day
        ORDER BY day
        """
        # Важно: укажем location, чтобы не было рассинхрона по региону
        job = client.query(sql, location=location)
        df = job.result().to_dataframe()  # тот же приём, что в твоём рабочем коде
        if not df.empty:
            total += int(df["billed_bytes"].fillna(0).sum())
    print(f"[DEBUG] {region}: billed_this_month_GB = { (df['billed_bytes'].sum()/1024**3) if not df.empty else 0 :.2f}")
    return total



def _sum_storage_bytes(
    client: bigquery.Client,
    regions: Iterable[str],
    project_id: Optional[str],
    ) -> int:
    """
    Итог логических байт хранения по проекту (active + long_term).
    Сначала пытаемся через TABLE_STORAGE_BY_PROJECT (рекомендуется),
    иначе — суммируем по датасетам в нужной локации.
    """
    if not project_id:
        project_id = client.project

    total_bytes = 0

    for region in regions:
        location = _region_to_location(region)

        # 1) Предпочтительный путь: агрегат по проекту
        try:
            sql = f"""
            SELECT COALESCE(SUM(active_logical_bytes + long_term_logical_bytes), 0) AS logical_bytes
            FROM `{region}`.INFORMATION_SCHEMA.TABLE_STORAGE_BY_PROJECT
            WHERE project_id = @project
            """
            job = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ScalarQueryParameter("project", "STRING", project_id)]
                ),
                location=location,
            )
            res = job.result()
            row = next(iter(res), None)
            if row and row["logical_bytes"] is not None:
                total_bytes += int(row["logical_bytes"])
                continue  # перешли к следующему региону
        except Exception:
            # пойдём фолбэком
            pass

        # 2) Фолбэк: собираем по датасетам нужной локации
        for ds in client.list_datasets(project=project_id):
            try:
                ds_ref = client.get_dataset(ds.reference)
                if (ds_ref.location or "").upper() != location:
                    continue
                sql = f"""
                SELECT COALESCE(SUM(active_logical_bytes + long_term_logical_bytes), 0) AS logical_bytes
                FROM `{project_id}.{ds_ref.dataset_id}.INFORMATION_SCHEMA.TABLE_STORAGE`
                """
                job = client.query(sql, location=ds_ref.location)
                res = job.result()
                row = next(iter(res), None)
                if row and row["logical_bytes"] is not None:
                    total_bytes += int(row["logical_bytes"])
            except Exception:
                continue

    return total_bytes


def estimate_query_bytes(client: bigquery.Client, sql: str, location: Optional[str] = None) -> int:
    """Dry‑run оценка, сколько байт обработает запрос (не запускает сам запрос)."""
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
        location=location
    )
    return int(job.total_bytes_processed)


def check_free_tier_allowance(
    client: bigquery.Client,
    *,
    project_id: Optional[str] = None,
    regions: Iterable[str] = DEFAULT_REGIONS,
    planned_query_sql: Optional[str] = None,
    planned_query_location: Optional[str] = None,
    query_limit_bytes: int = QUERY_LIMIT_BYTES,
    storage_limit_bytes: int = STORAGE_LIMIT_BYTES,
) -> Dict[str, int]:
    """
    Возвращает dict c использованием и лимитами.
    Если (использование + планируемый запрос) > лимита — кидает RuntimeError.
    """
    if not project_id:
        project_id = client.project

    used_query = _sum_query_bytes_billed(client, regions, project_id=project_id)
    used_storage = _sum_storage_bytes(client, regions, project_id)

    planned = 0
    if planned_query_sql:
        planned = estimate_query_bytes(client, planned_query_sql, location=planned_query_location)

    if used_query + planned > query_limit_bytes:
        remain_tb = (query_limit_bytes - used_query) / 1024**4
        raise RuntimeError(
            f"⛔ Превышение лимита запросов free‑tier.\n"
            f"Уже использовано: {used_query/1024**4:.3f} TB; "
            f"планируется к обработке: {planned/1024**4:.3f} TB; "
            f"доступно ещё ≈ {max(remain_tb, 0):.3f} TB."
        )

    if used_storage > storage_limit_bytes:
        raise RuntimeError(
            f"⛔ Превышение лимита хранения free‑tier.\n"
            f"Используется: {used_storage/1024**3:.2f} GB (лимит {storage_limit_bytes/1024**3:.0f} GB)."
        )

    return {
        "used_query_bytes": used_query,
        "planned_query_bytes": planned,
        "query_limit_bytes": query_limit_bytes,
        "used_storage_bytes": used_storage,
        "storage_limit_bytes": storage_limit_bytes,
    }


def safe_query(
    client: bigquery.Client,
    sql: str,
    *,
    location: Optional[str] = None,                  # где исполнять сам запрос (EU/US)
    regions: Iterable[str] = DEFAULT_REGIONS,        # где искать статистику джобов/хранения
    project_id: Optional[str] = None,
    query_limit_bytes: int = QUERY_LIMIT_BYTES,
    storage_limit_bytes: int = STORAGE_LIMIT_BYTES,
    to_dataframe: bool = True,                       # вернуть DataFrame или объект Job
    job_config: Optional[bigquery.QueryJobConfig] = None,
    timeout: Optional[float] = None,                 # секунд; None = ждать до конца
    fail_soft: bool = False                          # True = не падать, а вернуть None
) -> Union["bigquery.job.QueryJob", "pandas.DataFrame", None]:
    """
    Безопасный запуск BigQuery-запроса:
      1) dry-run оценка + проверка лимитов free-tier,
      2) печать строки "Storage xx/xx GB, Trafik yy/yy TB" (текущее использование/лимит),
      3) выполнение запроса только если всё ок,
      4) если fail_soft=True — при превышении лимита вернёт None и выведет предупреждение.
    """
    try:
        # Проверка лимитов с dry-run оценкой
        stats = check_free_tier_allowance(
            client,
            project_id=project_id,
            regions=regions,
            planned_query_sql=sql,
            planned_query_location=location,
            query_limit_bytes=query_limit_bytes,
            storage_limit_bytes=storage_limit_bytes,
        )
        # Форматированный вывод перед выполнением реального запроса
        storage_used_gb = stats["used_storage_bytes"] / 1024**3
        storage_limit_gb = stats["storage_limit_bytes"] / 1024**3
        query_used_tb   = stats["used_query_bytes"] / 1024**4
        query_limit_tb  = stats["query_limit_bytes"] / 1024**4
        print(f"Storage {storage_used_gb:.2f}/{storage_limit_gb:.0f} GB, "
              f"Trafik {query_used_tb:.3f}/{query_limit_tb:.0f} TB")
        
    except RuntimeError as e:
        if fail_soft:
            print(f"⚠️ Пропуск запроса: {e}")
            return None
        else:
            raise

    # Если не упало — выполняем
    job = client.query(sql, job_config=job_config, location=location)
    # print("client.project =", client.project)
    # print("regions =", list(DEFAULT_REGIONS))

    if to_dataframe:
        import pandas as pd  # noqa: F401
        return job.result(timeout=timeout).to_dataframe()

    return job