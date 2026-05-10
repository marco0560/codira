# ruff: noqa: E722


def broken() -> None:
    try:
        value = 1 / 0
        print(value)
    except:
        return
