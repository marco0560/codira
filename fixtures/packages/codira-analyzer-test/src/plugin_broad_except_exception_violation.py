# ruff: noqa: BLE001


def broken() -> None:
    try:
        value = 1 / 0
        print(value)
    except Exception:
        return
