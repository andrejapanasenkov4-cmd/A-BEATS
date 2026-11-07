# Сторонние компоненты и уведомления

A-BEATS использует сторонние компоненты, которые распространяются на условиях собственных лицензий:

- Google API Python Client — Apache License 2.0.
- Google Auth libraries — Apache License 2.0.
- Pillow — HPND License.
- tzdata — Apache License 2.0 / Public Domain, в зависимости от включённых данных.
- PyInstaller — GPL with bootloader exception (сборочный инструмент; не является частью исходного runtime-пакета приложения).
- FFmpeg — лицензия зависит от конфигурации сборки и включённых кодеков.

Первый запуск загружает FFmpeg Essentials build с `https://www.gyan.dev/ffmpeg/builds/`. Windows-сборка включает скачанный FFmpeg runtime. Перед коммерческим распространением собранного установщика проверьте лицензию конкретного бинарного файла и включённых кодеков; соблюдайте требования FFmpeg и сборщика. При необходимости замените runtime на собственную сборку FFmpeg с известной конфигурацией.

A-BEATS не заявляет авторство или владение этими сторонними компонентами. Ссылки на лицензии: `https://www.apache.org/licenses/LICENSE-2.0`, `https://python-pillow.org/`, `https://ffmpeg.org/legal.html`.
