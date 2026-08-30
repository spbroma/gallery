# roma's photos

Локальный прототип публичной фотогалереи. Исходный архив не изменяется: publish-скрипт читает финальные rating-папки, создаёт отдельные WebP-копии без EXIF/GPS и собирает единый `gallery.json`.

## Первый запуск

1. Проверьте пути и параметры в `config/gallery.config.json`.
2. Создайте небольшую превью-выборку: `npm run gallery:preview`.
3. Запустите сайт: `npm run dev`.

`config/gallery.preview.json` ограничивает прототип тремя съёмками и 12 фотографиями из каждой. Полная локальная публикация: `npm run gallery:publish`.

Для съёмки выбирается максимальная числовая папка `N`, у которой рядом существует непустая `N_black`. Съёмки без такой пары не публикуются. Имена файлов из `N_black` служат точным списком отбора, но web-производные строятся из соответствующих оригиналов в `N`, поэтому чёрные поля на сайт не попадают.

## Исключения

Исключения задаются в `config/gallery.exclusions.json` единым списком. Путь считается относительно корня фотоархива.

```json
{
  "exclude": [
    { "folder": "2026/07-11 - Musical" },
    { "folder": "2026/08-21 - Florence", "files": ["DSC04302.jpg", "DSC04318.jpg"] }
  ]
}
```

Запись без `files` исключает папку целиком со всем содержимым. Запись с `files` исключает только перечисленные файлы; имена сопоставляются без учёта регистра.

Frontend не зависит от хранилища: он читает URL из `public/data/gallery.json`. Граница адаптера Google Drive уже есть в `scripts/storage/google_drive.py`; сейчас она намеренно не выполняет загрузку. Для подключения Drive нужно реализовать upload/mirror sync, заполнить `storage.googleDrive` в конфиге и переключить `storage.provider` на `googleDrive`.

## Локальный анализ библиотеки

Источником истины служат JSON-sidecar-файлы внутри каждой съёмки: `_meta/photos/<photo-id>.json`. Анализатор берёт все фотографии из максимальной числовой папки съёмки, уменьшает временную копию для Gemma до 1000 px по длинной стороне, считает визуальные характеристики и embedding, а затем атомарно обновляет только машинную секцию sidecar. Ручные теги и редакторские поля он не изменяет.

Первичная миграция текущей агрегированной базы:

```bash
npm run gallery:meta:migrate          # только показать план
npm run gallery:meta:migrate -- --write
```

Локальная админка:

```bash
npm run gallery:admin
# http://127.0.0.1:4177
```

В админке можно менять публикацию, описание, масштаб кадра, число людей и ручные теги. Контурные теги созданы моделью; при нажатии они становятся ручными. Сохранение изменяет только соответствующий `_meta` JSON.

## Конвейер одной новой съёмки

Глобальная команда `photo_publish` установлена по той же схеме, что и `make_square`: реализация лежит в `~/work/utils/photo_publish.py`, а в `~/work/bin/photo_publish` находится ссылка, доступная через `PATH`. Настройки путей хранятся рядом в `~/work/utils/photo_publish.config.json`.

Команду запускают прямо из выбранной числовой папки:

```bash
cd "$HOME/Pictures/PhotoArchive/2026/08-30 - Regensburg/2"
photo_publish
```

Стадии выполняются отдельно и записываются в `_meta/pipeline.json`:

1. `square` — вызывает существующий `make_square` и создаёт `N_black`;
2. `metadata` — создаёт недостающие sidecar-файлы;
3. `analyze` — запускает локальные Gemma, OpenCV и SigLIP;
4. `publish-local` — добавляет съёмку в локальную копию сайта;
5. `verify` — сверяет манифесты и WebP-файлы;
6. `git-handoff` — показывает изменения и команды для Git, ничего не отправляя;
7. `release` — добавляет изменения репозитория, создаёт commit, отправляет его в настроенные remote/branch и тем самым запускает GitHub Pages.

После прерывания достаточно снова запустить `photo_publish`. Также доступны `photo_publish --from-stage 3`, `photo_publish --stage verify`, `photo_publish --force` и `photo_publish --list-stages`. Обычный запуск и `--force` доходят только до безопасной локальной стадии 6. Публикация всегда запускается отдельно и явно:

```bash
photo_publish --stage release
```

Стадия `release` выполняет `git diff --check`, `git add --all`, создаёт commit (если есть изменения) и делает push. Remote, branch и шаблон сообщения задаются в `photo_publish.config.json`; push в `main` запускает workflow `.github/workflows/pages.yml`.

`scripts/analyze_library.py` строит фиксированные теги и масштаб кадра через Ollama/Gemma, числовые характеристики цвета и света, средний HSV/RGB крупнейшего цветового кластера через OpenCV, а также нормализованный визуальный embedding SigLIP 2. Анализатор пишет результат только в `_meta` исходного архива. `publish.py` читает `published` и метаданные оттуда, зеркально обновляет WebP-файлы и создаёт в репозитории только необходимые публичные манифесты без описаний и embeddings.

```bash
uv venv .venv-analysis --python 3.12
uv pip install --python .venv-analysis/bin/python -r requirements-analysis.txt
npm run gallery:analyze
```

Пути, модели и адрес Ollama задаются в `config/analysis.config.json`. Повторный запуск пропускает изображения с тем же SHA-256, моделью и версией промпта; `--force` пересчитывает всё.
