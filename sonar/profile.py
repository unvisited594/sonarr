"""Профиль пользователя: имя и аватарка (config["profile"])."""
import random
from pathlib import Path

AVATAR_DIR = Path(__file__).resolve().parent / "assets" / "avatars"

# id, подпись (из имени файла аватарки), файл
AVATARS = [
    ("verity", "Verity (Верити)", "verity.jpg"),
    ("listening", "Прослушка", "listening.jpg"),
    ("chill", "Чилл", "chill.jpg"),
    ("vacation", "Отпуск", "vacation.jpg"),
    ("me", "Я", "me.jpg"),
    ("ban", "Бан", "ban.jpg"),
]

_ADJECTIVES = ("Ночной", "Бархатный", "Звёздный", "Лунный", "Тихий", "Солнечный", "Неоновый",
               "Северный", "Джазовый", "Ламповый", "Космический", "Винтажный")
_NOUNS = ("Слушатель", "Меломан", "Ритм", "Бит", "Грув", "Мотив", "Аккорд", "Тембр", "Диджей", "Бас")


def random_name(rng: random.Random | None = None) -> str:
    rng = rng or random
    return f"{rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)} {rng.randint(10, 99)}"


def avatar_path(avatar_id: str | None) -> Path | None:
    for aid, _title, file in AVATARS:
        if aid == avatar_id:
            path = AVATAR_DIR / file
            return path if path.exists() else None
    return None


def get(config) -> dict | None:
    return config.data.get("profile")


def save(config, name: str, avatar_id: str) -> dict:
    profile = {"name": name.strip(), "avatar": avatar_id}
    config.data["profile"] = profile
    config.save()
    return profile
