import requests
from datetime import date
from db import set_special_day, get_special_day


BRASILAPI_URL = "https://brasilapi.com.br/api/feriados/v1/{year}"


def fetch_national_holidays(year: int) -> list[dict]:
    response = requests.get(BRASILAPI_URL.format(year=year), timeout=10)
    response.raise_for_status()
    return response.json()


def import_holidays(year: int) -> tuple[int, int]:
    """
    Fetches national holidays for the given year and stores them as special_days.
    Skips dates already marked with a non-feriado type (user override takes precedence).
    Returns (imported_count, skipped_count).
    """
    holidays = fetch_national_holidays(year)
    imported = 0
    skipped = 0

    for holiday in holidays:
        iso_date = holiday.get("date")
        name = holiday.get("name", "Feriado nacional")

        if not iso_date:
            continue

        existing = get_special_day(iso_date)
        if existing and existing["day_type"] != "feriado":
            # User manually set this day — do not overwrite
            skipped += 1
            continue

        set_special_day(
            date=iso_date,
            day_type="feriado",
            notes=name,
        )
        imported += 1

    return imported, skipped


def import_current_and_next_year() -> tuple[int, int]:
    current_year = date.today().year
    total_imported = 0
    total_skipped = 0

    for year in (current_year, current_year + 1):
        try:
            imp, skp = import_holidays(year)
            total_imported += imp
            total_skipped += skp
        except requests.RequestException:
            pass

    return total_imported, total_skipped
