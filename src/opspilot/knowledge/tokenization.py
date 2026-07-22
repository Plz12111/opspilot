import re

TOKEN_PATTERN = re.compile(r"[a-z0-9_.-]+|[\u4e00-\u9fff]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    result: list[str] = []
    for token in TOKEN_PATTERN.findall(text.lower()):
        if "\u4e00" <= token[0] <= "\u9fff":
            result.extend(token)
            result.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            result.append(token)
    return result
